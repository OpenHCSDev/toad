package org.toadcomms;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import org.kivy.android.PythonActivity;

/**
 * The APK's activity (buildozer.spec's android.entrypoint): python-for-android's Qt activity,
 * which starts ConnectedService as Toad starts, so the process stays alive in the background.
 * Android 13 and later show the service's notification only with the notification
 * permission, which it asks for here; refused, the service still keeps the process.
 */
public class ToadActivity extends PythonActivity {

    private static final int NOTIFICATIONS_ASKED = 1;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATIONS_ASKED);
        }
        startForegroundService(new Intent(this, ConnectedService.class));
    }
}
