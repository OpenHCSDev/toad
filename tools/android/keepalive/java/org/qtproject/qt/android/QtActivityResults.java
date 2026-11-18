package org.qtproject.qt.android;

import android.content.Intent;

/**
 * Qt's activity-result entry for the APK's activity. QtActivityBase.onActivityResult hands
 * each result to Qt (QtNative.onActivityResult, package-private) after Activity's own;
 * python-for-android's PythonActivity overrides it to notify only its own listeners and never
 * calls super, so Qt's receivers (the native file dialog's among them) never heard an answer.
 * ToadActivity calls this in its place. It lives in Qt's package because that entry is
 * package-private.
 */
public final class QtActivityResults {

    private QtActivityResults() {
    }

    public static void deliver(int requestCode, int resultCode, Intent data) {
        QtNative.onActivityResult(requestCode, resultCode, data);
    }
}
