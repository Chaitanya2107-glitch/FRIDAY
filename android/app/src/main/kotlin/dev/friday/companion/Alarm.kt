package dev.friday.companion

import android.app.*
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Handler
import android.os.Looper
import androidx.core.app.NotificationCompat

object Alarm {
    private var player: MediaPlayer? = null
    private var oldVolume: Int? = null
    private val handler = Handler(Looper.getMainLooper())
    private var stopTask: Runnable? = null
    @Synchronized fun start(context: Context) {
        stop(context)
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("phone-ring", "Find my phone", NotificationManager.IMPORTANCE_HIGH))
        val stop = PendingIntent.getService(context, 71, Intent(context, SharingService::class.java).setAction("dev.friday.STOP_ALARM"), PendingIntent.FLAG_IMMUTABLE)
        manager.notify(72, NotificationCompat.Builder(context, "phone-ring").setSmallIcon(R.drawable.ic_friday)
            .setContentTitle("FRIDAY is ringing this phone").setContentText("Stops automatically after 30 seconds.")
            .setOngoing(true).setTimeoutAfter(30000).addAction(0, "Stop", stop).build())
        val audio = context.getSystemService(AudioManager::class.java)
        oldVolume = audio.getStreamVolume(AudioManager.STREAM_ALARM)
        try {
            audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0)
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
            player = MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                setDataSource(context, uri); isLooping = true; prepare(); start()
            }
            stopTask = Runnable { stop(context) }.also { handler.postDelayed(it, 30000) }
        } catch (_: Exception) {
            stop(context)
            context.repository.message = "Phone alarm could not play. Check alarm volume and Do Not Disturb settings."
        }
    }
    @Synchronized fun stop(context: Context) {
        stopTask?.let(handler::removeCallbacks); stopTask = null
        runCatching { player?.stop() }; player?.release(); player = null
        oldVolume?.let { volume -> runCatching { context.getSystemService(AudioManager::class.java).setStreamVolume(AudioManager.STREAM_ALARM, volume, 0) } }
        oldVolume = null
        context.getSystemService(NotificationManager::class.java).cancel(72)
    }
}
