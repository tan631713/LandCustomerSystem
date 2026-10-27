// The one place to bump the mobile web version. index.html loads this before
// the app scripts and service-worker.js imports it for its cache name; keep
// customer_version.MOBILE_ASSET_VERSION (reported by /health) equal to it.
self.LAND_MOBILE_ASSET_VERSION = 34;
