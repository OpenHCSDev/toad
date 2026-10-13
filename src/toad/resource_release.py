"""Exit stacks that complete resource release without losing earlier failures."""
from contextlib import AsyncExitStack, ExitStack
from functools import wraps


class CompleteRelease:
    """Keep each failure while the inherited stack consumes its callbacks."""

    def __init__(self):
        super().__init__()
        self._errors: list[BaseException] = []

    def _push_exit_callback(self, callback, is_sync=True):
        # This is contextlib's registration hook for both sync and async exits.
        # Recording here covers every callback without repeating error handling
        # at the resource owners. The inherited stack still owns order/consumption.
        errors = self._errors
        if is_sync:
            @wraps(callback)
            def complete(*details):
                try:
                    return callback(*details)
                except BaseException as error:
                    errors.append(error)
                    return False
        else:
            @wraps(callback)
            async def complete(*details):
                try:
                    return await callback(*details)
                except BaseException as error:
                    errors.append(error)
                    return False
        super()._push_exit_callback(complete, is_sync)

    def pop_all(self):
        release = super().pop_all()
        release._errors, self._errors = self._errors, []
        return release

    def _raise_errors(self):
        errors = self._errors.copy()
        self._errors.clear()
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("Resource release failed", errors)


class ResourceRelease(CompleteRelease, ExitStack):
    """Consume synchronous releases; none may suppress a failure."""

    def __exit__(self, error_type, error, traceback):
        if error is not None:
            self._errors.append(error)
        super().__exit__(None, None, None)
        self._raise_errors()
        return False


class AsyncResourceRelease(CompleteRelease, AsyncExitStack):
    """Consume mixed releases, preserving failures in execution order."""

    async def __aexit__(self, error_type, error, traceback):
        if error is not None:
            self._errors.append(error)
        await super().__aexit__(None, None, None)
        self._raise_errors()
        return False
