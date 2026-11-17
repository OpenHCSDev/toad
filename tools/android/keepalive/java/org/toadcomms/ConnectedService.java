package org.toadcomms;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

/**
 * Keeps the app's process in the foreground while Toad is open, so Android does not kill it
 * for memory once the reader switches away. It runs in the activity's own process (the
 * keep-alive manifest declares no process of its own): a service in a separate process, as
 * python-for-android's services are, would keep only itself alive.
 *
 * Its ongoing notification says Toad is connected; tapping it brings the open window back.
 * It ends with the process: closing Toad exits the process (Qt's QtActivityBase.onDestroy),
 * and the notification goes with it.
 */
public class ConnectedService extends Service {

    private static final String CHANNEL = "connection";
    private static final int NOTIFICATION = 1;

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(
                new NotificationChannel(CHANNEL, "Connection", NotificationManager.IMPORTANCE_LOW));
        Intent reopen = new Intent(this, ToadActivity.class)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        Notification notification = new Notification.Builder(this, CHANNEL)
                .setContentTitle("Toad comms connected")
                .setSmallIcon(getApplicationInfo().icon)
                .setOngoing(true)
                .setContentIntent(PendingIntent.getActivity(this, 0, reopen, PendingIntent.FLAG_IMMUTABLE))
                .build();
        // Android 14+ refuses startForeground() when the service is created from a
        // background-launch context (no visible activity, no whitelisted broadcast).
        // The keep-alive is meaningful only alongside a running window, so if Android
        // won't grant foreground status, the service has nothing to keep alive: stop
        // instead of letting the process crash.
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startForeground(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING);
            } else {
                startForeground(NOTIFICATION, notification);
            }
        } catch (android.app.ForegroundServiceStartNotAllowedException refused) {
            android.util.Log.w("toadcomms", "ConnectedService refused by platform; stopping", refused);
            stopSelf();
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // A process Android ends anyway starts cold: no window to keep, so no restart.
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
