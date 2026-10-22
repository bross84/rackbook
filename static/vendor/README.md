# Progress chart dependencies

Pinned browser scripts served from this folder; no CDN requests or build step. Each corresponding MIT license is included. Load Chart.js, Hammer.js, then the zoom plugin.

Chart.js 4.4.0 matches Hevy-Fatigue’s chart engine. Its `_trendChartBaseOptions`, `_vfBuildBarLineChart`, and `_exmBuildLineChart` in `static/index.html` informed Progress’s sizing, axes, typography, legends and tooltip styling. Rackbook retains its own data/calculations and uses real elapsed-time spacing.

## Chart.js 4.4.0

- File: `chart-4.4.0.umd.js`
- Source: https://registry.npmjs.org/chart.js/-/chart.js-4.4.0.tgz
- Archive member: `package/dist/chart.umd.js`
- SHA-256: `321e3a3fa98da4aaa957d10be57cbb514de0989eed8f9d726b5d05902cd01904`

## Hammer.js 2.0.8

- File: `hammer-2.0.8.min.js`
- Source: https://registry.npmjs.org/hammerjs/-/hammerjs-2.0.8.tgz
- Archive member: `package/hammer.min.js`
- SHA-256: `7953631f0e54794d2352a3cfa591c0914d73e14f90141058e3cf16bee7939bcf`

## chartjs-plugin-zoom 2.2.0

- File: `chartjs-plugin-zoom-2.2.0.min.js`
- Source: https://registry.npmjs.org/chartjs-plugin-zoom/-/chartjs-plugin-zoom-2.2.0.tgz
- Archive member: `package/dist/chartjs-plugin-zoom.min.js`
- SHA-256: `e4a088e5bab93be6ee47c939eeb9ebaa80e0b39156d4bdfd1af9c844be81b6c4`

To update, fetch the pinned upstream npm tarball and copy only the compiled browser file and license; never run package lifecycle scripts. Update the versioned HTML path and hashes, then run the Progress frontend/route checks and verify desktop/touch zoom, gaps, selection and theme handling in the browser.
