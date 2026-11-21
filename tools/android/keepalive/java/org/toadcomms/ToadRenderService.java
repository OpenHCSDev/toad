package org.toadcomms;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import org.kivy.android.PythonService;
import org.toadcomms.toadcomms.ServiceToadrender;

/**
 * Runs the renderer's Python entry in its own Android process.
 *
 * python-for-android's generated service loads {@code libmain.so}.  Its Qt bootstrap names
 * that same JNI library {@code libmain_<abi>.so}, because the activity's Qt loader selects
 * an ABI-qualified application library.  The generated service therefore dies before
 * Python starts.  This service keeps p4a's generated launch declaration, thread lifecycle
 * and native entry point, and owns the one Qt-specific difference: the library it loads.
 */
public final class ToadRenderService extends ServiceToadrender {

    private Intent launch;

    public static void start(Context context, String argument) {
        Intent intent = ServiceToadrender.getDefaultIntent(context, "", "toadcomms", "Toadrender", argument);
        intent.setClass(context, ToadRenderService.class);
        context.startService(intent);
    }

    public static void stop(Context context) {
        context.stopService(new Intent(context, ToadRenderService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        launch = intent;
        return super.onStartCommand(intent, flags, startId);
    }

    @Override
    public void run() {
        Bundle extras = launch.getExtras();
        System.loadLibrary("python3.14");
        System.loadLibrary("main_" + Build.SUPPORTED_ABIS[0]);
        PythonService.mService = this;
        nativeStart(
                extras.getString("androidPrivate"),
                extras.getString("androidArgument"),
                extras.getString("serviceEntrypoint"),
                extras.getString("pythonName"),
                extras.getString("pythonHome"),
                extras.getString("pythonPath"),
                extras.getString("pythonServiceArgument"));
        stopSelf();
    }
}
