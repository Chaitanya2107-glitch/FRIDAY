package dev.friday.companion

data class Explanation(val name: String, val text: String)
val explanations = linkedMapOf(
    "app_usage" to Explanation("App usage", "Usage Access lets FRIDAY read foreground app changes while your screen is on, about every 15 seconds. It sends package, app label, Android category and interval times. No screen contents, typing or accessibility data. Android will open its Usage Access settings next."),
    "screen" to Explanation("Screen", "Share screen on/off and unlock count. No screenshots or contents are captured. No special Android permission is needed."),
    "battery" to Explanation("Battery", "Share battery percentage and whether the phone is charging. No special Android permission is needed. Heartbeats include battery only while this signal is enabled."),
    "network" to Explanation("Network", "Share Wi-Fi/mobile/offline state. Home Wi-Fi is optional: after enabling this signal, the separate home button explains Location permission. Only a salted SSID hash is sent, never the Wi-Fi name. No browsing history or network traffic is read."),
    "motion" to Explanation("Motion", "Physical Activity permission lets Play Services report transitions into still, walking and in-vehicle states. FRIDAY sends only those states. No raw sensor samples or location coordinates are sent."),
    "places" to Explanation("Named places", "Name home, college or library and enter a geofence locally. Android needs precise and background location for enter/leave callbacks. FRIDAY does not request GPS samples or send coordinates: only the name and entered/left. Background location is a separate Settings step."),
    "audio_devices" to Explanation("Audio devices", "Share headphones/Bluetooth-audio connection changes and the audio device label. On Android 12+, Nearby devices permission is needed for Bluetooth labels. No microphone or audio recording."),
    "media" to Explanation("Now playing", "Notification-listener access is powerful: Android allows it to see notifications. FRIDAY uses it here only to discover media sessions and share now-playing app, title and artist. Ordinary notification content is not read. This signal is separate from notification metadata."),
    "notifications" to Explanation("Notification metadata", "Notification-listener access can expose notification contents, so grant it only if you trust this app. FRIDAY sends package, posted time and category only. It never reads notification title/text/extras. The local per-app content preference starts empty and cannot bypass the laptop's metadata-only receiver."),
    "sleep" to Explanation("Sleep", "Ask Health Connect for read-only daily sleep duration aggregates. No raw sessions or location leave the phone. Background reads are a separate optional grant; without that, FRIDAY reads while this screen is open."),
    "steps" to Explanation("Steps", "Ask Health Connect for read-only daily step totals. No raw steps, routes or GPS leave the phone. Background reads are a separate optional grant; without that, FRIDAY reads while this screen is open."),
    "interruption" to Explanation("Interruption mode", "Share current Do Not Disturb filter and ringer mode. FRIDAY only reads this state; it cannot change DND or silence calls.")
)
