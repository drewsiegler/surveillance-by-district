# Surveillance by District

How many license plate reader cameras are in your district? This website counts every automated license plate reader (ALPR) that volunteers have mapped in Santa Clara County, by the districts that represent the people who drive past it: cities, city council districts, county supervisors, Congress, the state legislature, school and college districts and their trustee areas, the County Board of Education, open space and Valley Water districts.

**[Open the site →](https://drewsiegler.github.io/surveillance-by-district/)**

It's rebuilt every morning with the latest camera map, and it's free: no account, nothing to install, and nothing to download unless you want the numbers.

## What it shows

- **A map of the county** shaded by how many cameras each district has, with a dot for every camera. Point at a district (or tap it on a phone) for its count, how many were made by Flock Safety, the other makers, and any agency or business mapped as running them.
- **A ranked table** for whichever map you pick, with the officeholder named next to each district where District Lookup has one, like `3—Cm. Anthony Tordillos`.
- **Downloads**: every district on every map as one CSV for a spreadsheet, and a JSON file that adds the location, maker and operator of each camera.

The address bar remembers which map you're looking at, so a link like `…/surveillance-by-district/#council_district` opens straight to council districts.

## Reading the numbers

- **Each count is a floor, not a census.** A camera counts only once someone has found it and mapped it, so a neighborhood nobody has walked looks less watched than it is. Know of one that's missing? Add it on [DeFlock](https://deflock.me); it shows up here the next day.
- **Districts on the same electoral map** (council, supervisor, Congress, legislature, trustee areas) each hold about the same number of residents, so their counts compare fairly. Cities and school districts vary widely in size.
- **Council districts and trustee areas** count only cameras inside the city or school district that drew them, the same rule District Lookup uses for addresses.
- **Elsewhere in the county** collects cameras outside every area on a map. On the city map, that's unincorporated land.

## Where the data comes from

- **Cameras:** [OpenStreetMap](https://www.openstreetmap.org), where DeFlock and other volunteers map license plate readers, read through the free [Overpass API](https://overpass-api.de). Each morning's answer is saved in `data/alpr_cameras.json`, and the repo's history records every day the map changed.
- **Districts:** [District Lookup](https://github.com/drewsiegler/district-lookup), the free tool that finds every district an address is in. This site doesn't keep its own copy of the maps. Each build pulls District Lookup's latest maps and its matching rules, so the two always agree, and a map fixed there is fixed here the next morning. The page says which version of District Lookup it was built from.

## Your visit stays private

The page is one self-contained file. It loads no scripts, fonts, map tiles, ads or analytics from anywhere, and it keeps no cookies. The only server your browser talks to is GitHub Pages, which hosts it and, like any website, sees your internet address when you visit.

## Running it yourself

Needs Python 3.10 or newer, and a copy of District Lookup beside this folder:

```bash
git clone https://github.com/drewsiegler/district-lookup
git clone https://github.com/drewsiegler/surveillance-by-district
cd surveillance-by-district
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python src/build.py      # asks OpenStreetMap for fresh cameras, then builds site/
python -m pytest         # about 4 seconds, no internet needed
```

Open `site/index.html` in a browser to see the result. `python src/build.py --offline` builds from the saved cameras without going online. If District Lookup lives somewhere else, say where: `python src/build.py --district-lookup ~/code/district-lookup`.

**For another county:** set District Lookup up with that county's maps (its [docs/adding-maps.md](https://github.com/drewsiegler/district-lookup/blob/main/docs/adding-maps.md) explains how) and point this at it. The camera search follows the area District Lookup's maps cover, so the only Santa Clara County words left to change are the heading and description at the top of `src/page.html`.

## How it's published

`.github/workflows/build-site.yml` runs every morning at 6:17 Pacific, on every push, and from **Actions → Build the site → Run workflow**. It clones the latest District Lookup, runs the tests, builds the site and publishes it to GitHub Pages. If OpenStreetMap is down, it builds from the last saved cameras, so a District Lookup map fix still goes out. If a test fails, nothing is published that day, and GitHub emails the repo's owner.

GitHub pauses a scheduled workflow in a repo that's had no activity for 60 days. The workflow's own commits (on days the camera map changes) usually keep it going; if it ever stops, the Actions tab has a button to turn it back on.

## Support this project

Surveillance by District is free and always will be. If it helps your organizing, you can leave a tip at **[ko-fi.com/andrewsiegler](https://ko-fi.com/andrewsiegler)**. It's a personal project, not a nonprofit, so tips aren't tax-deductible, and they're never required. Sharing the site, or mapping a missing camera on DeFlock, helps just as much.

## License

Copyright © 2026 Drew Siegler. The code is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0), the same as District Lookup: free to use and adapt, and anyone who publishes a modified version has to publish their source under the same license.

**The data isn't covered by that license.**

- Camera locations are © OpenStreetMap contributors, available under the [Open Database License](https://opendatacommons.org/licenses/odbl/) (ODbL). If you share the counts, credit OpenStreetMap; the CSV's last row has the wording.
- District boundaries come from District Lookup, which gets them from Census TIGER files (public domain) and from each agency's GIS portal or public records request, with whatever terms those agencies set. [District Lookup's README](https://github.com/drewsiegler/district-lookup#license) has the details.
