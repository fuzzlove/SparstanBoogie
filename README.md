SparstanBoogie's origins were tested reportedly on iOS/iPadOS 15.2 - 16.7 RC (20H18) and 17.0 however, tests have been conducted up to (26.1 <) where it actually quit working. Lower level testing is needed and welcome as far as testing on devices that are (> 26.1). Also any testing on devices above or under whats been reported is welcomed as it may come back in newer devices so theres no reason to shrug off any good samaritans that would like to report if this works for them or not. Older devices that were claimed to be unsupported by the grandfather programs this stemed from have been found to be affected such as iOS 15.8.7.

This issue was reportedly addressed with improved handling of symlinks according to faithful vulnerability disclosure. This issue was supposedly fixed in iOS 17.7.1 and iPadOS 17.7.1, iOS 18.1 and iPadOS 18.1, tvOS 18.1, visionOS 2.1. Restoring a maliciously crafted backup file may lead to modification of protected system files. However, SparstanBoogie implements techniques seen in Nugget and Misaka to give the user more control over the process of customizing their device with this semi-jailbreak tool.

There are two main ways to implement this for customization, 1. the tool endorses the use of trollstore to show impact of replacing user-land system and Mobile applications (The application comes with trollstorehelper to demonstrate replacement). 2. The tool uses a partial iOS restore to gain control and overwrite system files which can be seen by the overwriting of the gestalt file. Users can customize their operating system by looking up known gestalt keys and replacing or overwriting their values.

Usage: python3.12 main.py trollstorehelper --target Tips

Update: Now utilizing directory traversal and iOS restore to make significant changes. Thank you to everyone involved with Misaka26, Nugget, and TrollRestore for the inspiration. If this project fails you I highly suggest checking them out. This project just gives a more verbose educational value from the command line of what those tools were for.

Top Used Syntax:
  Sparse app-target:
    python3 main.py <from_path> --target "Tips"
  Gestalt-chain:
    python3 main.py <from_path> --gestalt-chain

Examples:

python3 main.py trollrestorehelper --target "Calculator"

python3 main.py MobileGestalt.plist --gestalt-chain


__________

Below you will find a guide so that you can pull your own gestalt file and make changes to your iOS device.

# Pulling Your MobileGestalt File Using Shortcuts + a-Shell mini

This guide explains how to use the [Save MobileGestalt Shortcut](https://routinehub.co/shortcut/23246/) together with a-Shell mini to export your device’s MobileGestalt cache and save it as:

```text
MobileGestalt.plist
```

The shortcut was specifically designed to save a copy of:

```text
com.apple.MobileGestalt.plist
```

Newer iOS versions require a-Shell mini for reliable access/export behavior.

---

# What Is MobileGestalt?

`MobileGestalt` is an Apple system framework that stores device-specific configuration and hardware information.

Researchers and advanced users commonly use the plist to:

- View device capabilities
- Extract hardware identifiers
- Preserve original device configuration data
- Analyze feature flags and internal settings

The exported plist is unique to your device and contains details specific to your hardware configuration.

---

# Requirements

You will need:

- An iPhone or iPad
- Shortcuts
- a-Shell mini
- Files app access enabled

---

# Step 1 — Install a-Shell mini

Install **a-Shell mini** from the App Store.

a-Shell mini is recommended because newer iOS releases tightened Shortcut filesystem behavior, and the shortcut uses a-Shell mini to reliably access/export the MobileGestalt file.

After installing:

1. Open a-Shell mini once
2. Allow any requested permissions
3. Close it

This initializes its working directories for the Shortcut.

---

# Step 2 — Install the Shortcut

Open:

https://routinehub.co/shortcut/23246/

Then:

1. Tap **Get Shortcut**
2. Review the actions
3. Tap **Add Shortcut**

You should now see:

```text
Save MobileGestalt
```

inside your Shortcuts library.

---

# Step 3 — Run the Shortcut

Launch the shortcut.

Depending on iOS version, you may see prompts requesting:

- File access
- iCloud Drive access
- Permission to communicate with a-Shell mini

Allow all requested permissions.

The shortcut will then:

1. Access the MobileGestalt cache
2. Export the plist
3. Save a copy to Files/a-Shell storage

---

# Step 4 — Locate the Exported File

Open the Files app.

Navigate to one of these locations:

```text
On My iPhone
→ a-Shell
```

or:

```text
iCloud Drive
→ Shortcuts
```

Depending on your iOS version and configuration, the file may appear as:

```text
com.apple.MobileGestalt.plist
```

Rename it to:

```text
MobileGestalt.plist
```

if needed.

---

# Step 5 — Verify the File

You should now have:

```text
MobileGestalt.plist
```

This file can be:

- Shared to a Mac
- Opened in a plist editor
- Used with research utilities
- Archived as a backup of your device-specific configuration

---

# Why a-Shell mini Is Recommended

Using a-Shell mini is currently one of the most reliable methods because it allows the shortcut to work around newer iOS Shortcut export restrictions.

It also makes it easier to:

- Access exported files directly
- Move plist files between apps
- Inspect device-specific information locally

---

# Optional: Inspect Device Details

Once exported, the plist can be opened with tools such as:

- Plist editors
- Python scripts
- MobileGestalt parsing utilities
- Research shortcuts

Additional related utility:

- MobileGestalt Device Info Shortcut  
  https://routinehub.co/shortcut/4920/

---
