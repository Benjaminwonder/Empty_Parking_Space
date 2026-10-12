# Handoff — DK
Only DK writes here. Newest entry at the bottom. Format: see BRIDGES.md.

9-30-26 DK1 
Created the initial ParkFind webpage in Java with a campus parking interface, search bar, parking filters, parking lot markers, ADA/EV options, and navigation screen. The page runs through a local HTTP server. The initial prototype used sample parking data and a local “Last updated” time. →DK-2: replace the hard-coded parking layout with SK-LAYOUT from lot_commuter_north.json.


10-5-26 DK2
Updated the Java webpage to use the shared parking layout file instead of maintaining a separate list of parking stalls in Java. The layout defines the lot ID, zones, rows, stalls per row, and ADA/EV stall designations. Fixed the StringBuilder concatenation issue encountered during development. → DK-3: use SK-VIEW as the source of parking status instead of relying on sample occupancy values.


10-12-26 DK3
Set up and ran the Python backend using server.py and the parkfind package, organizing clock.py, lastseen.py, and event.py so the required imports work correctly. Created a test feed at runs/feed.jsonl and confirmed that the SK-VIEW endpoint at http://localhost:8765/view returns valid parking-status JSON with HTTP 200 responses. Connected the Java webpage to SK-VIEW using the endpoint URL in WebPage.java and implemented JavaScript fetch() requests with an approximately five-second refresh interval. Tested the parking-status display and confirmed that N1-01 and N1-02 display their expected taken/free states during testing, while all other stalls remain unknown when no valid status reports are available. Changed the test feed for N1-01 to occupied and observed that the webpage displayed it as taken, providing evidence that the updated status was reflected on the page. The basic backend connection and status-display test are working. Still need to complete verification that the status change occurs automatically without manually refreshing the webpage, and confirm that timestamps, claim ages, and zone-level counts consistently come from the backend but from the crude testing i've done so far,it seems like it consistently but more needs to be done.→ Complete the remaining SK-VIEW integration checks before proceeding to DK-4.
