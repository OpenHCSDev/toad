package org.kivy.android;

import android.os.SystemClock;

/** Disarm python-for-android's unconditional onKeyDown back-click toast. */
public final class PythonActivityAccess {
    private PythonActivityAccess() {}

    public static void disarmBackToast(PythonActivity activity) {
        activity.lastBackClick = SystemClock.elapsedRealtime();
    }
}
