# Preserved historical review probes

These six files are byte-identical to the migration baseline. Their bare imports
and old layout belong to the pinned source trees they inspect. Invoke the migrated
`research/campaigns/hp/dgpN_probes.py --source CHECKOUT ...` entry point: current
checkout probes use canonical imports; historical targets execute these originals
in a fresh isolated process whose local imports are restricted to that target.
Missing target modules are refused before inference. Never use current modules to
fill a missing historical dependency.
