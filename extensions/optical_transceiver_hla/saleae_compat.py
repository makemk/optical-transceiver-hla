# Centralised import of the Saleae Logic 2 HLA API.
#
# Under Logic 2 the real `saleae.analyzers` package is present. Outside it (the
# offline unit tests and the simulation script) it is not, so we fall back to
# minimal stand-ins that preserve the real constructor contract:
#
#   * MetaHighLevelAnalyzer.__call__ STRIPS `settings` before calling __init__ -
#     so an HLA's __init__ must not take a settings argument.
#   * settings are assigned as instance attributes by __new__ before __init__
#     runs, and a missing setting raises before the object is usable.
#
# Keeping the two paths behaviourally identical is what lets the same decoder
# source run inside Logic 2 and under `python tools/test_*.py`.

try:
    from saleae.analyzers import HighLevelAnalyzer, AnalyzerFrame, ChoicesSetting

    FROM_LOGIC2 = True

except ImportError:  # pragma: no cover - exercised only outside Logic 2
    FROM_LOGIC2 = False

    class _Setting:
        def __init__(self, *, label=None):
            self.label = label
            self.name = None

        def validate(self, v):
            pass

        def _serialize(self):
            return {}

    class ChoicesSetting(_Setting):
        def __init__(self, choices, **kwargs):
            super().__init__(**kwargs)
            self.choices = tuple(choices)

    class _MetaHLA(type):
        def __call__(cls, settings=None, *args, **kwargs):
            obj = cls.__new__(cls, settings, *args, **kwargs)
            obj.__init__(*args, **kwargs)
            return obj

    class HighLevelAnalyzer(metaclass=_MetaHLA):
        @classmethod
        def _get_settings(cls):
            import inspect
            res = []
            for k, v in inspect.getmembers(cls):
                if isinstance(v, _Setting):
                    v.name = k
                    res.append(v)
            return res

        def __new__(cls, settings=None, *args, **kwargs):
            obj = super().__new__(cls)
            for s in cls._get_settings():
                setattr(obj, s.name,
                        (settings or {}).get(s.name,
                                            s.choices[0] if hasattr(s, 'choices') else ''))
            return obj

    class AnalyzerFrame:
        def __init__(self, type: str, start_time, end_time, data: dict = None):
            self.type = type
            self.start_time = start_time
            self.end_time = end_time
            self.data = data or {}
