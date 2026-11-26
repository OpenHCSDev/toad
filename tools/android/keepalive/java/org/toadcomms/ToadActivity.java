package org.toadcomms;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.drawable.ColorDrawable;
import android.os.Build;
import android.os.Bundle;
import android.system.ErrnoException;
import android.system.Os;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;
import org.kivy.android.PythonActivity;
import org.qtproject.qt.android.QtActivityResults;

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

    /** Keep-alive / IME bottom inset handoff file read by QtToadApp.fit_safe_area so
     *  QtWindow's OnLayoutChangeListener (which queries raw getRootWindowInsets() and ignores
     *  the folded IME inset below) can never drop the bottom margin while the keyboard is up. */
    private int lastReportedImeBottomPx = -1;

    private void writeImeBottomPx(java.io.File file, int px) {
        if (px == lastReportedImeBottomPx) {
            return;
        }
        lastReportedImeBottomPx = px;
        try (java.io.FileOutputStream out = new java.io.FileOutputStream(file)) {
            out.write(Integer.toString(px).getBytes(java.nio.charset.StandardCharsets.US_ASCII));
        } catch (java.io.IOException ignored) {
        }
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Keep Android's window and decor background black so opening the soft keyboard or
        // resizing never exposes Android's default white windowBackground behind Qt's surface.
        getWindow().setBackgroundDrawable(new ColorDrawable(Color.BLACK));
        getWindow().getDecorView().setBackgroundColor(Color.BLACK);
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
        final java.io.File imeFile = new java.io.File(getCacheDir(), "ime_bottom_px");
        writeImeBottomPx(imeFile, 0);
        try {
            Os.setenv("QT_ANDROID_DISABLE_ACCESSIBILITY", "1", true);
            Os.setenv("TOAD_IME_INSET_FILE", imeFile.getAbsolutePath(), true);
        } catch (ErrnoException failure) {
            android.util.Log.e("toadcomms", "could not set Toad Android environment variables", failure);
        }
        super.onCreate(savedInstanceState);
        // Android 15 (targetSdk 35) enforces edge-to-edge and stops resizing the activity
        // window for SOFT_INPUT_ADJUST_RESIZE; Qt's QtWindow.getSafeInsets only reads
        // systemBars() | displayCutout(), and QtActivityDelegate's keyboardGeometryChanged
        // uses deprecated Display.getMetrics() which under-counts the keyboard by ~290 px.
        // Resizing android.R.id.content with setPadding() resizes QtRootLayout's SurfaceView
        // and flashes white on EGL reallocation. Instead, fold WindowInsets.Type.ime().bottom
        // into systemBars().bottom via WindowInsets.Builder AND record the real IME bottom
        // in TOAD_IME_INSET_FILE: QtWindow receives the exact IME inset through
        // safeAreaMarginsChanged with zero SurfaceView resize, and QtToadApp.fit_safe_area
        // ignores stale getRootWindowInsets() reads fired by QtWindow.onLayoutChange.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            final View content = findViewById(android.R.id.content);
            if (content != null) {
                content.setOnApplyWindowInsetsListener((view, insets) -> {
                    Insets nav = insets.getInsets(WindowInsets.Type.navigationBars());
                    int imeBottom = insets.getInsets(WindowInsets.Type.ime()).bottom;
                    int reportedIme = imeBottom > nav.bottom ? imeBottom : 0;
                    writeImeBottomPx(imeFile, reportedIme);
                    if (reportedIme == 0) {
                        return insets;
                    }
                    return new WindowInsets.Builder(insets)
                            .setInsets(
                                    WindowInsets.Type.navigationBars(),
                                    Insets.of(nav.left, nav.top, nav.right, reportedIme))
                            .build();
                });
                content.requestApplyInsets();
            }
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATIONS_ASKED);
        }
    }

    /** The keep-alive may start only while this activity is actually in the foreground.
     *  Android rejects a foreground-service launch from onCreate when a cold launch occurs
     *  while the device is dozing. That refusal is about the optional keep-alive, not the
     *  window or renderer, so it must not abort either one. */
    @Override
    protected void onResume() {
        super.onResume();
        try {
            startForegroundService(new Intent(this, ConnectedService.class));
        } catch (android.app.ForegroundServiceStartNotAllowedException refused) {
            android.util.Log.w("toadcomms", "ConnectedService refused while activity resumed", refused);
        }
    }

    /** python-for-android's PythonActivity.onKeyDown forgets to check KEYCODE_BACK and
     *  intercepts every key event (including Android soft-keyboard digits 0-9) with a
     *  "Click again to close the app" toast; Toad handles Qt.Key_Back in Python (go_back).
     *  Disarm the p4a timer so every key reaches QtActivityBase.onKeyDown directly. */
    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        org.kivy.android.PythonActivityAccess.disarmBackToast(this);
        return super.onKeyDown(keyCode, event);
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
