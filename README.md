## 💻 KettleBrain Project
 
The **KettleBrain** app is an electric brewing kettle control system. Up to 3 heating elements up to 1500W/120V or 2000W/250V each can be controlled (up to 4500W/120V or 6000W/250V total).

Currently tested only on the Raspberry Pi 3B running Debian Trixie and Bookworm. Should work with RPi4 and RPi5 running the same OS's but not yet tested.

Please **donate $$** if you use the app. 

![Support QR Code](src/assets/support.gif)

## 💻 Suite of Apps for the Home Brewer
**🔗 [KettleBrain Project](https://github.com/keglevelmonitor/kettlebrain)** An electric brewing kettle control system

**🔗 [FermVault Project](https://github.com/keglevelmonitor/fermvault)** A fermentation chamber control system

**🔗 [KegLevel Lite Project](https://github.com/keglevelmonitor/keglevel_lite)** A keg level monitoring system

**🔗 [BatchFlow Project](https://github.com/keglevelmonitor/batchflow)** A homebrew batch management system

**🔗 [TempMonitor Project](https://github.com/keglevelmonitor/tempmonitor)** A temperature monitoring and charting system


## To Install the App

Open **Terminal** and run this command. Type carefully and use proper uppercase / lowercase because it matters:

```bash
bash <(curl -sL bit.ly/install-kettlebrain)
```

That's it! You will now find the app in your application menu under **Other**. You can use the "Check for Updates" function inside the app to install future updates.

## 🔗 Detailed installation instructions

Refer to the detailed installation instructions for specific hardware requirements and complete wiring & hookup instructions:

👉 (placeholder for installation instructions)

## ⚙️ Summary hardware requirements

Required
* Raspberry Pi 3B (should work on RPi 4 but not yet tested)
* Debian Trixie OS (not tested on any other OS)
* [placeholder for hardware requirements]

## To uninstall the app

To uninstall, run the same install command. When the menu appears, select **UNINSTALL**:

```bash
bash <(curl -sL bit.ly/install-kettlebrain)
```

## ⚙️ For reference
Installed file structure:

```
~/kettlebrain/
|-- utility files...
|-- src/
|   |-- application files...
|   |-- assets/
|       |-- supporting files...
|-- venv/
|   |-- python3 & dependencies
~/kettlebrain-data/
|-- user data...
    
Required system-level dependencies are installed via sudo apt outside of venv.

```
