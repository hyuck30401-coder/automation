# -*- coding: utf-8 -*-
"""화면(GUI) 없는 환경에서 분석 모듈을 import 할 수 있게 해주는 tkinter 스텁.

왜 필요한가
-----------
cdf_compare_tool.py 4~5번 줄이 모듈 최상단에서 tkinter 를 import 한다.
그런데 tkinter 가 실제로 쓰이는 곳은 438번 줄 `class CdfCompareApp(tk.Tk)`
부터이고, CLAUDE.md §2 에 적힌 대로 그 GUI 클래스는 웹 빌드에서 도달 불가능한
죽은 코드다.

결과적으로 tkinter 가 설치되지 않은 환경(CI 러너, 서버, 컨테이너)에서는
분석 코드를 부르기도 전에 ImportError 로 죽는다. 회귀 검증을 자동화하려면
이 벽을 넘어야 한다.

이 모듈은 **기존 소스를 한 글자도 고치지 않고** sys.modules 에 가짜 tkinter 를
미리 꽂아서 그 벽을 우회한다. import 하는 것만으로 효과가 발생한다.

    import headless   # 이 한 줄이 스텁을 심는다
    import cdf_compare_web

주의
----
- 진짜 tkinter 가 이미 설치되어 있으면 아무것도 하지 않는다 (Windows 개발 환경).
  즉 님 PC 에서의 동작은 전혀 달라지지 않는다.
- 스텁 클래스를 실제로 인스턴스화하려 하면 즉시 RuntimeError 를 낸다.
  GUI 코드가 조용히 실행되어 이상한 결과를 내는 것보다, 시끄럽게 죽는 편이 낫다.
- 분석 경로(analyze_to_json / analyze_fail_to_json)는 GUI 를 만들지 않으므로
  이 스텁에 닿지 않는다.
"""

import sys
import types

__all__ = ["is_stubbed", "ensure_headless"]

_STUBBED = False


def _build_stub_module(name):
    module = types.ModuleType(name)

    class _GuiStub:
        """어떤 속성 접근이든 자기 자신을 돌려주는 더미. 인스턴스화는 거부한다."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "headless 모드에서는 GUI 를 만들 수 없습니다 "
                "(요청된 클래스: {}). 분석 함수만 호출하세요.".format(name)
            )

        def __getattr__(self, attr):
            return _GuiStub

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    def _module_getattr(attr):
        # tk.Tk, tk.StringVar, ttk.Frame ... 무엇을 찾든 클래스를 돌려준다.
        # class CdfCompareApp(tk.Tk) 처럼 '상속 대상'으로 쓰이므로 클래스여야 한다.
        return _GuiStub

    module.__getattr__ = _module_getattr
    module._GuiStub = _GuiStub
    return module


def ensure_headless():
    """tkinter 가 없으면 스텁을 심는다. 이미 있으면 손대지 않는다.

    Returns:
        True  - 스텁을 심었다 (헤드리스 환경)
        False - 진짜 tkinter 가 있어서 아무것도 하지 않았다
    """
    global _STUBBED

    try:
        import tkinter  # noqa: F401
        return False
    except ImportError:
        pass

    for name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk"):
        if name not in sys.modules:
            sys.modules[name] = _build_stub_module(name)

    _STUBBED = True
    return True


def is_stubbed():
    """지금 가짜 tkinter 를 쓰고 있는가."""
    return _STUBBED


# import 만으로 효과가 나도록 즉시 실행
ensure_headless()
