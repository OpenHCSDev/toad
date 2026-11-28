package org.toadcomms;

import android.app.Activity;
import android.content.ClipData;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Log;
import android.util.SparseArray;
import java.util.ArrayList;
import java.util.List;

/**
 * What a composer's Attach opens on the phone: Android's own chooser - the apps that give a
 * file (Files, Photos, Drive) and the camera - in place of the document picker alone.
 *
 * Attach opens Qt's file dialog (toad.qt.file_pickers); on Android Qt answers it with an
 * ACTION_OPEN_DOCUMENT intent through the activity. ToadActivity offers that intent here: it
 * becomes ACTION_GET_CONTENT for the same types in a chooser, with a camera capture into a
 * new MediaStore photo as the chooser's first choice. The answer goes back to Qt's dialog as
 * a content URI either way: the app's own, or the photo the camera wrote, which it returns no
 * URI for. Qt's dialog reads it as it reads any picked file.
 */
final class AttachChooser {

    private static final String TAG = "toadcomms";

    private final Activity activity;
    /** The photo each offered request's camera would write, by request code. */
    private final SparseArray<Uri> photos = new SparseArray<>();

    AttachChooser(Activity activity) {
        this.activity = activity;
    }

    /** The intent to start for `intent`: a file dialog's document request becomes the chooser. */
    Intent offered(Intent intent, int requestCode) {
        if (intent == null || !Intent.ACTION_OPEN_DOCUMENT.equals(intent.getAction())
                || !intent.hasCategory(Intent.CATEGORY_OPENABLE)) {
            return intent;
        }
        Intent content = new Intent(Intent.ACTION_GET_CONTENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .setType(intent.getType() != null ? intent.getType() : "*/*");
        if (intent.hasExtra(Intent.EXTRA_MIME_TYPES)) {
            content.putExtra(Intent.EXTRA_MIME_TYPES, intent.getStringArrayExtra(Intent.EXTRA_MIME_TYPES));
        }
        boolean allowMultiple = intent.getBooleanExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
        content.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, allowMultiple);
        Intent chooser = Intent.createChooser(content, "Attach");
        List<Intent> initial = new ArrayList<>();
        if (allowMultiple && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            // Android 13+'s Photo Picker opens directly in checkbox multi-select mode,
            // unlike ACTION_GET_CONTENT providers that default to single-tap selection.
            Intent photoPicker = new Intent(MediaStore.ACTION_PICK_IMAGES)
                    .putExtra(MediaStore.EXTRA_PICK_IMAGES_MAX, MediaStore.getPickImagesMaxLimit());
            initial.add(photoPicker);
        }
        Uri photo = newPhoto();
        if (photo != null) {
            Intent capture = new Intent(MediaStore.ACTION_IMAGE_CAPTURE)
                    .putExtra(MediaStore.EXTRA_OUTPUT, photo)
                    .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            capture.setClipData(ClipData.newRawUri("", photo));
            initial.add(capture);
            photos.put(requestCode, photo);
        }
        if (!initial.isEmpty()) {
            chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, initial.toArray(new Intent[0]));
        }
        return chooser;
    }

    /** The answer Qt's dialog reads for an offered request: the camera's photo when it was the camera,
     *  and ClipData-only when multiple files were picked so Qt reads every URI instead of stopping at getData(). */
    Intent answered(int requestCode, int resultCode, Intent data) {
        Uri photo = photos.get(requestCode);
        if (photo != null) {
            photos.remove(requestCode);
            ContentResolver resolver = activity.getContentResolver();
            boolean picked = data != null && (data.getData() != null || data.getClipData() != null);
            try {
                if (resultCode == Activity.RESULT_OK && !picked) {
                    // The camera wrote the photo and answers with no URI of its own.
                    ContentValues taken = new ContentValues();
                    taken.put(MediaStore.MediaColumns.IS_PENDING, 0);
                    resolver.update(photo, taken, null, null);
                    return new Intent().setData(photo).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                }
                resolver.delete(photo, null, null);
            } catch (RuntimeException failure) {
                Log.e(TAG, "could not settle the camera's photo " + photo, failure);
            }
        }
        return normalizeMultiSelect(resultCode, data);
    }

    /** Qt 6's QAndroidPlatformFileDialogHelper checks intent.getData() before intent.getClipData()
     *  and returns only that first URI whenever a picker populates both. Clearing data keeps
     *  ClipData and its granted read permissions intact so Qt iterates all selected URIs. */
    private static Intent normalizeMultiSelect(int resultCode, Intent data) {
        if (resultCode == Activity.RESULT_OK && data != null) {
            ClipData clip = data.getClipData();
            if (clip != null && clip.getItemCount() > 1 && data.getData() != null) {
                data.setData(null);
            }
        }
        return data;
    }

    /** A pending photo in Pictures/Toad for the camera to write, or null where it cannot be made. */
    private Uri newPhoto() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return null; // RELATIVE_PATH and IS_PENDING arrived in Android 10.
        }
        ContentValues photo = new ContentValues();
        photo.put(MediaStore.MediaColumns.DISPLAY_NAME, "Toad " + System.currentTimeMillis() + ".jpg");
        photo.put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg");
        photo.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/Toad");
        photo.put(MediaStore.MediaColumns.IS_PENDING, 1);
        try {
            return activity.getContentResolver().insert(
                    MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), photo);
        } catch (RuntimeException failure) {
            Log.e(TAG, "could not make a photo for the camera", failure);
            return null;
        }
    }
}
