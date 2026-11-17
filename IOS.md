# Nexus on iPhone

There are two ways to get it onto an iPhone, and both run the same page (`index.html`):

1. **Web app.** Students open the Nexus in Safari and add it to their home screen. It gets its
   own icon, runs full screen and works offline. No App Store and no fee. This works as soon as
   these files are pushed to GitHub Pages.
2. **iOS app.** The same page packaged by [Capacitor](https://capacitorjs.com) into a native app
   you build in Xcode. You can run it in the Simulator or on your own iPhone with just a Mac.
   You need the paid Apple Developer Program only for TestFlight and the App Store.

## What changed in the page

- Added a mobile `viewport` tag. Before this, iPhone Safari drew the desktop layout at 980px
  wide and shrank it, so the phone layout in the CSS never applied.
- The page now respects the notch and home indicator (`env(safe-area-inset-*)`) and uses
  `100dvh`, so Safari's toolbars no longer cover the bottom of the map. Dragging no longer
  makes the page bounce.
- On touch screens the search box uses 16px text, so iOS no longer zooms in when you tap it.
  Buttons and search results have bigger tap targets, and the hint reads "Tap… Pinch to zoom".
- `manifest.webmanifest`, `sw.js` and `icons/` make it installable and offline-capable.
- `viewer.template.html` now includes the PROJECT520 header link that had been added only to
  `index.html`, so a rebuild no longer drops it.

## 1. Web app (do this first)

1. Rebuild the page from the template as usual, then publish it as `index.html`:
   `python3 build.py --out=index.html`. Commit `index.html` along with `manifest.webmanifest`,
   `sw.js` and `icons/`, and push.
2. On an iPhone, open `https://projectfivetwenty.com/nexus/` in Safari and tap
   **Share → Add to Home Screen**.
3. Open it once while online. After that it works with no connection. When you publish a new
   build, students get it the next time they open the app while online.

You never need to edit `sw.js` when you change the map.

## 2. iOS app on your Mac (no developer account needed yet)

One-time setup:

1. Install **Xcode** from the Mac App Store and open it once so it can install the iOS platform.
2. Install **Node.js 20 or newer** from nodejs.org.
3. In this folder, run:
   ```
   npm install
   npm install @capacitor/core @capacitor/ios
   npm install -D @capacitor/cli
   npm run app:bundle
   npx cap add ios --packagemanager SPM
   npm run app:sync
   ```
   `app:bundle` copies the page, Cytoscape and the fonts into `www/` so the app needs no
   internet. `cap add ios` creates the Xcode project in `ios/`. The second run (`app:sync`) also
   installs `icons/icon-1024.png` as the app icon. Commit the `ios/` folder.

Run it:

- **Simulator:** `npm run app:open` opens Xcode. Pick an iPhone simulator at the top and press ▶.
- **Your own iPhone (free Apple ID):**
  1. In Xcode, open **Settings → Accounts** and add your Apple ID.
  2. Select the **App** target. Under **Signing & Capabilities**, set Team to
     "Your Name (Personal Team)".
  3. Plug in the iPhone and tap **Trust**. On the iPhone, turn on
     **Settings → Privacy & Security → Developer Mode** (it restarts).
  4. Choose the phone at the top of Xcode and press ▶. The first time, the iPhone asks you to
     trust the developer under **Settings → General → VPN & Device Management**.
  5. Apps signed with a free account stop opening after 7 days. Press ▶ again to refresh it.

After every map change: `python3 build.py --out=index.html`, then `npm run app:sync`, then ▶.

## 3. App Store (when you're ready)

- **Enroll** in the Apple Developer Program ($99/year). An *Individual* account lists your
  personal name as the seller. An *Organization* account can list "Project 520", but it needs a
  legal entity (an LLC, for example) and a free D-U-N-S number, which adds days or weeks.
- **App Store Connect:** create the app with bundle ID `com.projectfivetwenty.nexus` and
  category Education. You also need a privacy policy URL; a short page on your site is enough.
  The app collects nothing, so the privacy label is "Data Not Collected". That holds as long
  as `app:bundle` reports no font warning, because then the app makes no third-party requests.
- **Screenshots:** take them in the Simulator with ⌘S, at the device sizes App Store Connect
  asks for.
- **Upload:** in Xcode, choose **Product → Archive → Distribute App → App Store Connect**. Test
  through TestFlight first.
- **Review risk.** Apple's guideline 4.2 (Minimum Functionality) rejects apps that are "just a
  website". This app works fully offline and never loads your site, which helps. Adding one or
  two native touches before submitting makes it safer, for example a haptic tap when focusing a
  topic or the native share sheet for a concept.
- **Links to coaching.** The header link opens projectfivetwenty.com in Safari, which is the
  low-risk setup for a free app. Keep prices and "buy" buttons out of the app itself.
