package org.toadcomms;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.system.ErrnoException;
import android.system.Os;
import android.view.WindowManager;
import org.kivy.android.PythonActivity;
import org.qtproject.qt.android.QtActivityResults;
import org.toadcomms.toadcomms.ServiceToadrender;

/**
 * The APK's activity (buildozer.spec's android.entrypoint): python-for-android's Qt activity,
 * which starts ConnectedService as Toad starts, so the process stays alive in the background.
 * Android 13 and later show the service's notification only with the notification
 * permission, which it asks for here; refused, the service still keeps the process.
 */
public class ToadActivity extends PythonActivity {

    private static final int NOTIFICATIONS_ASKED = 1;

    /** Attach's chooser: what Qt's file dialog asks the activity for becomes Android's own. */
    private final AttachChooser attachChooser = new AttachChooser(this);

    /**
     * The optimization level the app's Python runs at: 1 drops asserts and keeps docstrings,
     * which name every menu action and key (MenuDeclaration.key_summary,
     * ApplicationAction.summary). python-for-android's activity sets PYTHONOPTIMIZE=2, which
     * strips them, so every summary was blank on the phone. The APK's bytecode is compiled at
     * this level (tools/android/assemble.py reads it here), so the files it ships are the ones
     * this interpreter loads.
     */
    static final String PYTHON_OPTIMIZE = "1";

    /** python-for-android's activity sets the interpreter's environment through this, before
     *  Qt starts Python; the optimization level it sets is replaced by the app's. */
    @Override
    public void setEnvironmentVariable(String key, String value) {
        super.setEnvironmentVariable(key, "PYTHONOPTIMIZE".equals(key) ? PYTHON_OPTIMIZE : value);
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // The composer is part of the app's visible window, not a surface the keyboard may
        // cover. Resizing the window leaves Qt's layout in charge: history gives up height,
        // while Composer derives its shared viewport limit and then scrolls within it.
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
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
        ServiceToadrender.start(this, "");
    }

    @Override
    protected void onDestroy() {
        ServiceToadrender.stop(this);
        super.onDestroy();
    }

    /** Every activity start passes here (the two-argument form calls this one); a file
     *  dialog's document request is offered Android's chooser in its place. */
    @Override
    public void startActivityForResult(Intent intent, int requestCode, Bundle options) {
        super.startActivityForResult(attachChooser.offered(intent, requestCode), requestCode, options);
    }

    /** python-for-android's override notifies its own listeners and never calls super, so Qt's
     *  receivers heard no result; each result reaches both here, as QtActivityBase would. */
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        Intent answered = attachChooser.answered(requestCode, resultCode, data);
        super.onActivityResult(requestCode, resultCode, answered);
        QtActivityResults.deliver(requestCode, resultCode, answered);
    }
}
