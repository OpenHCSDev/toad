"""The APK's entry point: the APK's environment first, then Toad's Qt client.

The environment is entered before anything else imports, because the libraries it sets up
read it when they are imported (toad.qt.android_app).
"""

from toad.qt.android_app import enter

enter()

from toad.qt.android import main

main()
