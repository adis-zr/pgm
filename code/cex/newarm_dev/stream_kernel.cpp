#include <cmath>
#include <cstdint>
#include <cfloat>
#include <cfenv>
#include <ctime>
#include <new>
#include <vector>
#include <limits>
#include <algorithm>

// Strict binary64, no reassociation/FMA. Runtime checks reject a changed FP env.
static_assert(DBL_MANT_DIG==53 && std::numeric_limits<double>::is_iec559,
              "binary64 required");
struct V { double x; uint64_t e; };
// HOST CLOCK ADAPTER (11 Nov 2026, shared by both arms): the deadline is an ABSOLUTE value of the SAME clock Python's time.monotonic() reads on this host --
// Linux: CLOCK_MONOTONIC; Apple: CLOCK_UPTIME_RAW (= mach_absolute_time, the implementation of time.monotonic on macOS; pauses during host sleep exactly as Python's clock does).
#if defined(__APPLE__)
#define CEX_DEADLINE_CLOCK CLOCK_UPTIME_RAW
#else
#define CEX_DEADLINE_CLOCK CLOCK_MONOTONIC
#endif
static double now_mono(){ timespec ts; if(clock_gettime(CEX_DEADLINE_CLOCK,&ts)) return std::numeric_limits<double>::infinity(); return double(ts.tv_sec)+1e-9*ts.tv_nsec; }
struct Kernel {
 uint64_t adds=0,muls=0,updates=0,configs=0; int status=0; double deadline=0;
 void poll(){ if(now_mono()>=deadline)status=2; if(std::fegetround()!=FE_TONEAREST)status=3; }
 V add(V a,V b) {
  volatile double z=a.x+b.x; ++adds;
  if (!std::isfinite(z) || (z>0 && (z<2*DBL_MIN || z>DBL_MAX/2))) status=1;
  uint64_t e=std::max(a.e,b.e)+1; if(e >= (uint64_t(1)<<52)) status=4;
  return {z,e};
 }
 V mul(V a,V b) {
  volatile double z=a.x*b.x; ++muls;
  if (!std::isfinite(z) || (a.x>0 && b.x>0 && (z<2*DBL_MIN || z>DBL_MAX/2))) status=1;
  uint64_t e=a.e+b.e+1; if(e >= (uint64_t(1)<<52)) status=4;
  return {z,e};
 }
};
struct Tree {
 size_t base; std::vector<V> t; Kernel* k;
 Tree(const std::vector<double>& x, Kernel* kk):k(kk) {
  k->poll();
  base=1;while(base<x.size())base*=2;
  t.assign(2*base,{1.0,0});
  for(size_t i=0;i<x.size();++i)t[base+i]={x[i],1};
  for(size_t i=base-1;i>0;--i){t[i]=k->mul(t[2*i],t[2*i+1]);if((i&1023)==0)k->poll();}
  k->poll();
 }
 void set(size_t i,double x) {
  i+=base;t[i]={x,1};
  while(i>1){i/=2;t[i]=k->mul(t[2*i],t[2*i+1]);}
  ++k->updates;
 }
 V root()const{return t[1];}
};
extern "C" int stream_run(int m,int n,const double* phi,const double* rho,
 const double* psi,double deadline_abs,double* nums,uint64_t* exps,double* zout,
 uint64_t* ezout,uint64_t* counts) {
 try {
 Kernel k; k.deadline=deadline_abs; k.poll(); if(k.status)return k.status;
 if(std::fegetround()!=FE_TONEAREST || m<0 || n<0 || m>=63) return 3;
 // Linux CPython time.monotonic and this CLOCK_MONOTONIC share one epoch/suspend policy.
 std::vector<double> leaves(std::max(1,m),1.0);
 for(int i=0;i<m;++i)leaves[i]=phi[2*i];
 Tree ut(leaves,&k);
 std::vector<Tree> qt;qt.reserve(2*n);
 for(int j=0;j<n && !k.status;++j)for(int b=0;b<2 && !k.status;++b){
  std::vector<double> x(m+1,1.0);x[0]=rho[2*j+b];
  for(int i=0;i<m;++i)x[i+1]=psi[4*(i*n+j)+b];
  qt.emplace_back(x,&k); k.poll();
 }
 V Z={0,0};std::vector<V> N(m+n,{0,0}),ss(n),pre(n+1);
 const uint64_t total=uint64_t(1)<<m;
 for(uint64_t step=0;step<total;++step){
  if((step&1023)==0){
   k.poll(); if(k.status)break;
  }
  if(k.status)break;
  uint64_t gray=step^(step>>1);
  if(step){
   int i=__builtin_ctzll(step);int a=(gray>>i)&1;
   ut.set(i,phi[2*i+a]);
   for(int j=0;j<n;++j){for(int b=0;b<2;++b)
    qt[2*j+b].set(i+1,psi[4*(i*n+j)+2*a+b]);
    if((j&1023)==0)k.poll();
   }
  }
  for(int j=0;j<n;++j)ss[j]=k.add(qt[2*j].root(),qt[2*j+1].root());
  pre[0]=ut.root();for(int j=0;j<n;++j)pre[j+1]=k.mul(pre[j],ss[j]);
  V W=pre[n];Z=k.add(Z,W);
  for(int i=0;i<m;++i)if((gray>>i)&1)N[i]=k.add(N[i],W);
  V suffix={1,0};
  for(int j=n-1;j>=0;--j){
   V term=k.mul(k.mul(pre[j],qt[2*j+1].root()),suffix);
   N[m+j]=k.add(N[m+j],term);suffix=k.mul(suffix,ss[j]);
  }
  ++k.configs;
 }
 k.poll();
 counts[0]=k.configs;counts[1]=k.adds;counts[2]=k.muls;counts[3]=k.updates;
 *zout=Z.x;*ezout=Z.e;
 for(int i=0;i<m+n;++i){nums[i]=N[i].x;exps[i]=N[i].e;}
 return k.status;
 }catch(const std::bad_alloc&){return 5;}catch(...){return 6;}
}
