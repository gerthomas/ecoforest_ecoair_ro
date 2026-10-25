from datetime import timedelta

DOMAIN = "ecoforest_ecoair_ro"
MANUFACTURER = "Ecoforest"

# 1 minute default; sometimes needs a gap between data reads
POLLING_INTERVAL = timedelta(seconds=60)

# Controller family: "ecoair" (air-source block reads) or "geo" (original ecoGEO register reads)
CONF_FAMILY = "family"
