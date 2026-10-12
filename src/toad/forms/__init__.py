"""Forms drawn from dataclass declarations, over an ObjectState.

formbridge reads the declarations and says what a form contains; ObjectState
holds the values, what has changed since the last save, and who is told. The
widgets here show that and send edits back. Nothing in this package knows what
the form is for.
"""
