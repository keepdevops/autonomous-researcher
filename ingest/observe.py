def emit(status: str, detail: str = "", **metadata) -> None:
    try:
        from observer import ensure, publish
        from observer.events import Component, EventKind, SystemEvent

        ensure()
        publish(
            SystemEvent(
                component=Component.INGEST,
                kind=EventKind.STORAGE,
                status=status,
                detail=detail,
                metadata=metadata,
            )
        )
    except Exception:
        pass
