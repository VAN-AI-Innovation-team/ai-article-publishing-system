# Source configuration

`config/sources.yaml` is the editable source registry data. Add or update source entries here without changing Python code.

`url` is the approved source site. Put the RSS feed address in `feed_url`; it is required before an `rss` source can be activated.

Only activate a source after its collection method, priority, polling interval, and usage terms are confirmed. Supported methods are `rss` and `api`; polling intervals are stored in seconds.
