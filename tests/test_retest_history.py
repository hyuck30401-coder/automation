# -*- coding: utf-8 -*-
"""파일 내 재시험(retest-as-repeated-rows) 이력 재구성 단위 테스트 (통계개선_프롬프트.md §S6).

실제 Test Data 는 22개 fail 유닛의 마지막 Bin 이 전부 fail 이라 회복(Intermittent)
케이스를 실데이터로 검증할 수 없다 -- 그래서 합성 픽스처만 사용한다. 이 저장소에는
pytest 가 없다: python tests/test_retest_history.py 로 단독 실행.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

import cdf_compare_web as w

FAILURES = []


def check(name, condition):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")
        FAILURES.append(name)


LOWER, UPPER = 1.0, 9.0


def rec(sample, value, bin_, row_index, device_id="", lower=LOWER, upper=UPPER):
    return {
        "sample": sample,
        "value": value,
        "bin": bin_,
        "row_index": row_index,
        "device_id": device_id,
        "lower_limit": lower,
        "upper_limit": upper,
    }


def build_synthetic_records():
    """6개 유닛을 담은 가상의 '파일 하나' 를 만든다.

    S1 (DEVICE_ID=D1): 1회차 fail(Bin15) -> 2회차 fail(Bin17) -> 3회차 pass(Bin1)
        => 유닛 회복, row_index 1-3.
    S2: 1회차~3회차 전부 fail(Bin15)                => 기존 분류 유지, row_index 4-6.
    S3: 1회차만 존재, pass(Bin1) (재시험 없음)        => 영향 없음, row_index 7.
    S4: 1회차~4회차 fail(Bin15) -> 5회차 pass(Bin1)   => 재시험 4회 이상, 유닛 회복, row_index 8-12.
    S5: 1회차 fail -> 2회차 pass(단, Bin 은 여전히 fail, 다른 항목이 물고 있음) ->
        3회차 fail -> 4회차 pass(Bin1, 유닛 회복)      => 유닛 회복 + 항목 flip-flop 동시,
        row_index 13-16. §S6b 시나리오 1: Intermittent 가 우선.
    S6: 1회차 fail -> 2회차 pass(Bin 은 여전히 fail) -> 3회차 fail -> 4회차 fail(Bin
        도 fail, 유닛 최종 fail)                        => 항목 flip-flop 이지만 유닛은
        회복하지 못함, row_index 17-20. §S6b 시나리오 2: Unstable. (실데이터 VSTART
        Serial 25/62 와 동일한 패턴.)

    V2 는 S1 의 각 행에만 곁들여, row_index 로 항목을 같은 물리적 행으로 묶는 로직이
    항목 간에 뒤섞이지 않는지 함께 확인한다.
    """
    records = {"V1": [], "V2": []}

    # S1: row_index 1-3, DEVICE_ID join. V2 는 스펙과 무관한 곁다리 항목(한도 없음) --
    # row_index 그룹핑이 항목 간에 뒤섞이지 않는지만 확인하는 용도.
    records["V1"].append(rec("S1", 15.0, "15", 1, device_id="D1"))
    records["V2"].append(rec("S1", 50.0, "15", 1, device_id="D1", lower=None, upper=None))
    records["V1"].append(rec("S1", 12.0, "17", 2, device_id="D1"))
    records["V2"].append(rec("S1", 51.0, "17", 2, device_id="D1", lower=None, upper=None))
    records["V1"].append(rec("S1", 5.0, "1", 3, device_id="D1"))
    records["V2"].append(rec("S1", 52.0, "1", 3, device_id="D1", lower=None, upper=None))

    # S2: row_index 4-6, 계속 fail
    records["V1"].append(rec("S2", 20.0, "15", 4))
    records["V1"].append(rec("S2", 18.0, "15", 5))
    records["V1"].append(rec("S2", 16.0, "15", 6))

    # S3: row_index 7, 재시험 없음
    records["V1"].append(rec("S3", 5.0, "1", 7))

    # S4: row_index 8-12, 재시험 4회 (5회차에 회복)
    records["V1"].append(rec("S4", 20.0, "15", 8))
    records["V1"].append(rec("S4", 19.0, "15", 9))
    records["V1"].append(rec("S4", 18.0, "15", 10))
    records["V1"].append(rec("S4", 17.0, "15", 11))
    records["V1"].append(rec("S4", 5.0, "1", 12))

    # S5: row_index 13-16, 유닛 회복(Bin1) + 항목 중간 flip-flop 동시
    records["V1"].append(rec("S5", 15.0, "15", 13))
    records["V1"].append(rec("S5", 5.0, "17", 14))
    records["V1"].append(rec("S5", 15.0, "15", 15))
    records["V1"].append(rec("S5", 5.0, "1", 16))

    # S6: row_index 17-20, 항목 flip-flop 하지만 유닛은 최종 fail (실데이터 VSTART 25/62 패턴)
    records["V1"].append(rec("S6", 15.0, "15", 17))
    records["V1"].append(rec("S6", 5.0, "17", 18))
    records["V1"].append(rec("S6", 15.0, "15", 19))
    records["V1"].append(rec("S6", 15.0, "15", 20))

    return records


def test_stage_history_from_records():
    print("stage_history_from_records")
    records = build_synthetic_records()
    history = w.stage_history_from_records(records)

    check("DEVICE_ID 를 join_key 로 사용 (S1 -> D1)", "D1" in history and "S1" not in history)
    check("S1(D1) 이력 3단계", len(history.get("D1", [])) == 3)
    check("S2 이력 3단계", len(history.get("S2", [])) == 3)
    check("S3 이력 1단계 (재시험 없음)", len(history.get("S3", [])) == 1)
    check("S4 이력 5단계 (재시험 4회)", len(history.get("S4", [])) == 5)

    d1 = history["D1"]
    check("row_index 순서 보존 (S1 1회차 Bin=15)", d1[0]["bin"] == "15")
    check("row_index 순서 보존 (S1 3회차 Bin=1)", d1[2]["bin"] == "1")
    check(
        "같은 물리적 행의 V1/V2 가 한 occurrence 로 묶임 (뒤섞이지 않음)",
        d1[0]["items"]["V1"]["value"] == 15.0 and d1[0]["items"]["V2"]["value"] == 50.0
        and d1[2]["items"]["V1"]["value"] == 5.0 and d1[2]["items"]["V2"]["value"] == 52.0,
    )


def test_sample_states_from_history():
    print("sample_states_from_history")
    records = build_synthetic_records()
    history = w.stage_history_from_records(records)
    states = w.sample_states_from_history(history)

    for key in ("S1", "S2", "S3", "S4"):
        check(f"{key} 가 sample_states 에 존재", key in states)

    s1, s2, s3, s4 = states["S1"], states["S2"], states["S3"], states["S4"]

    # 요구사항 2: 회복 유닛(1회차 fail -> 마지막 Bin pass) = Intermittent
    check("S1 is_intermittent == True (1회차 fail -> 마지막 pass)", s1["is_intermittent"] is True)
    check("S2 is_intermittent == False (마지막도 fail)", s2["is_intermittent"] is False)
    check("S3 is_intermittent == False (재시험 없음, pass 유닛)", s3["is_intermittent"] is False)
    check("S4 is_intermittent == True (재시험 4회 후 회복)", s4["is_intermittent"] is True)

    # 요구사항 1: 대표 측정값 = 마지막 회차 (바뀌면 안 됨)
    check("S1 대표값 = 3회차 값 5.0", w.latest_record_for_sample_item(s1, "V1")["value"] == 5.0)
    check("S2 대표값 = 3회차 값 16.0", w.latest_record_for_sample_item(s2, "V1")["value"] == 16.0)
    check("S4 대표값 = 5회차 값 5.0", w.latest_record_for_sample_item(s4, "V1")["value"] == 5.0)

    # Bin 출처 통일: 대표값과 같은 마지막 회차의 Bin (이전엔 첫 회차 Bin과 어긋났음, CLAUDE.md §3-4)
    check("S1 final_bin = 마지막 회차(Bin=1)", s1["final_bin"] == "1")
    check("S4 final_bin = 마지막 회차(Bin=1)", s4["final_bin"] == "1")
    check("S2 final_bin = 마지막 회차(Bin=15)", s2["final_bin"] == "15")

    check("S1 final_pass == True", s1["final_pass"] is True)
    check("S2 final_pass == False", s2["final_pass"] is False)
    check("S3 final_pass == True (단일 pass 유닛, 영향 없음)", s3["final_pass"] is True)
    check("S3 stages 1개 (재시험 없어도 정상 동작)", len(s3["stages"]) == 1)


def test_fail_type_for_detail_intermittent():
    print("fail_type_for_detail (Intermittent / Unstable 분기, §S6b)")
    records = build_synthetic_records()
    history = w.stage_history_from_records(records)
    states = w.sample_states_from_history(history)

    def classify(state, item):
        item_history = w.item_history_for_sample(state, item)
        initial_record = item_history[0][1] if item_history else None
        value = w.latest_record_for_sample_item(state, item)["value"]
        return w.fail_type_for_detail(
            initial_record, item_history, value, LOWER, UPPER,
            mea_s=0.0, diff_s=None, n=0, sigma=None, mean=None,
            unit_recovered=bool(state.get("is_intermittent")),
        )

    # 시나리오 1: 1회차 fail -> 2회차 fail -> 3회차 pass, 유닛 회복(unit_recovered) => Intermittent
    check("S1/V1 => Intermittent (유닛 회복)", classify(states["S1"], "V1") == "Intermittent")

    # 시나리오 2: 1회차 fail -> ... -> 마지막 fail, 항목도 계속 fail => 기존 분류 유지
    result_s2 = classify(states["S2"], "V1")
    check("S2/V1 => Intermittent 아님 (유닛 회복 아님)", result_s2 != "Intermittent")
    check("S2/V1 => Unstable 아님 (항목이 중간에 pass 한 적 없음)", result_s2 != "Unstable")
    check("S2/V1 => Excessive (margin >= 1%, 기존 로직 그대로)", result_s2 == "Excessive")

    # 재시험 4회 이상에서도 유닛 회복이 정상 검출되는지 => Intermittent
    check("S4/V1 => Intermittent (재시험 4회 후 유닛 회복)", classify(states["S4"], "V1") == "Intermittent")

    # 시나리오(§S6b 요구 1): 유닛 회복 + 항목도 중간에 flip-flop => Intermittent 우선
    # (유닛이 살아났으면 그게 더 상위 사실이므로, 항목이 개별적으로 흔들렸는지는 따지지 않는다)
    check("S5/V1 => Intermittent (유닛 회복 + 항목 flip-flop 동시, 우선순위 검증)",
          classify(states["S5"], "V1") == "Intermittent")

    # 시나리오(§S6b 요구 2): 유닛 최종 fail + 항목만 중간에 flip-flop => Unstable
    # (실데이터 VSTART Serial 25/62 와 동일한 패턴 -- 유닛은 안 살아났으므로 벤치 대상)
    check("S6/V1 => Unstable (유닛 최종 fail, 항목만 flip-flop)",
          classify(states["S6"], "V1") == "Unstable")
    check("S6/V1 => Intermittent 아님 (유닛 회복 아님)", classify(states["S6"], "V1") != "Intermittent")


def test_analyze_bypass_condition():
    print("analyze_fail_to_json 게이트 통과 조건 (fail_samples / per-item bypass)")
    records = build_synthetic_records()
    history = w.stage_history_from_records(records)
    states = w.sample_states_from_history(history)

    # fail_samples 필터: not state_is_pass(state) or state.get("is_intermittent")
    def is_fail_sample(state):
        return (not w.state_is_pass(state)) or state.get("is_intermittent")

    check("S1 은 fail_samples 에 포함 (최종 pass 지만 회복 유닛)", is_fail_sample(states["S1"]) is True)
    check("S2 는 fail_samples 에 포함 (여전히 fail)", is_fail_sample(states["S2"]) is True)
    check("S3 는 fail_samples 에서 제외 (일반 pass 유닛, 영향 없음)", is_fail_sample(states["S3"]) is False)
    check("S4 는 fail_samples 에 포함 (최종 pass 지만 회복 유닛)", is_fail_sample(states["S4"]) is True)

    # 항목별 게이트: 최종값이 spec 통과라도, is_intermittent 이고 1회차에 그 항목이
    # 실제로 fail 했다면 통과시킨다 (cdf_compare_web.py analyze_fail_to_json 내부 로직과 동일 조건).
    def item_gate_passes(state, item):
        latest = w.latest_record_for_sample_item(state, item)
        if w.spec_status(latest.get("value"), latest.get("lower_limit"), latest.get("upper_limit")) in ("low", "high"):
            return True
        if not state.get("is_intermittent"):
            return False
        item_history = w.item_history_for_sample(state, item)
        if not item_history:
            return False
        first_record = item_history[0][1]
        return w.spec_status(
            first_record.get("value"), first_record.get("lower_limit"), first_record.get("upper_limit")
        ) in ("low", "high")

    check("S1/V1 최종값은 pass 지만 게이트 통과 (1회차 fail)", item_gate_passes(states["S1"], "V1") is True)
    check("S4/V1 최종값은 pass 지만 게이트 통과 (1회차 fail)", item_gate_passes(states["S4"], "V1") is True)
    check("S3/V1 게이트 통과 안 함 (1회차부터 pass, 회복 유닛 아님)", item_gate_passes(states["S3"], "V1") is False)


def main():
    test_stage_history_from_records()
    test_sample_states_from_history()
    test_fail_type_for_detail_intermittent()
    test_analyze_bypass_condition()

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)}개 실패 - {FAILURES}")
        sys.exit(1)
    print("PASS: 전부 통과")
    sys.exit(0)


if __name__ == "__main__":
    main()
