package org.toadcomms;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.system.ErrnoException;
import android.system.Os;
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
        // Qt's accessibility bridge stays off: any enabled accessibility service (on this
        // phone, Fluid Navigation Gestures; TalkBack is off) makes Qt's QtAccessibilityDelegate
        // answer the service's node-tree queries through QtAndroidAccessibility::
        // runInObjectContext, which holds the deadlock protector while a new window's EGL
        // surface is being created, so every popup, dropdown, dialog and keyboard show can
        // abort the app (SIGABRT "Failed to acquire deadlock protector for
        // QAndroidPlatformOpenGLWindow::eglSurface()"). Qt's own guard reads
        // QT_ANDROID_DISABLE_ACCESSIBILITY in QtAccessibilityDelegate's state listener, which
        // runs when super.onCreate builds Qt's layout - before Python starts - so the variable
        // is set here, first. The cost: a screen reader cannot read Toad.
        try {
            Os.setenv("QT_ANDROID_DISABLE_ACCESSIBILITY", "1", true);
        } catch (ErrnoException failure) {
            android.util.Log.e("toadcomms", "could not disable Qt's accessibility bridge", failure);
        }
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATIONS_ASKED);
        }
        startForegroundService(new Intent(this, ConnectedService.class));
    }
}
