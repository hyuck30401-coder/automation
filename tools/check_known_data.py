# -*- coding: utf-8 -*-
"""Known 데이터셋의 기대 판정과 툴의 실제 판정을 대조한다."""
import os, sys
sys.path.insert(0, os.path.abspath('_automation')); sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('tools'))
import headless, cdf_compare_web as web
from make_known_data import CASES, FAIL_KINDS, DEVICE, FOLDER, POST_UNITS, expected_reason

# 케이스 종류 -> 기대 결과
EXPECT_FAIL_TYPE = {'Excessive': 'Excessive', 'Slight': 'Slight', 'Tail': 'Tail',
                    'Unstable': 'Unstable', 'Intermittent': 'Intermittent', 'Tail2': 'Tail',
                    'Bnd:Excessive+': 'Excessive', 'Bnd:Excessive-': 'Slight',
                    'Bnd:Slight+': 'Slight', 'Bnd:Slight-': 'Tail'}
EXPECT_PASS_REASON = {'Measured': 'Measured', 'Delta': 'Delta',
                      'Measured + Delta': 'Measured + Delta',
                      'Marginal(Measured)': 'Measured', 'Marginal(Delta)': 'Delta',
                      'Marginal(Measured + Delta)': 'Measured + Delta',
                      'Bnd:Mea+': 'Measured', 'Bnd:Delta+': 'Delta',
                      'Bnd:Tau+': 'Measured', 'Bnd:Tau-': 'Measured'}
EXPECT_NONE = {'Bnd:Mea-', 'Bnd:Delta-'}          # 임계 바로 아래 — 안 걸려야 한다
FOLDED_KINDS = {'Marginal(Measured)', 'Marginal(Delta)', 'Marginal(Measured + Delta)', 'Bnd:Tau-'}

web.DATA_ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else 'Known Data')
from _regression_lib import analyze_condition
combo = {'device': DEVICE, 'ver': 'KV1-0', 'lot': 'K001', 'purpose': 'K01',
         'folder': FOLDER, 'item': 'HTOL', 'readout': '1000hrs', 'ft_temp': 'Room'}

exp_fail = {c['serial']: c for c in CASES if c['kind'] in EXPECT_FAIL_TYPE}
exp_pass = {c['serial']: c for c in CASES if c['kind'] in EXPECT_PASS_REASON}
exp_none = {c['serial']: c for c in CASES if c['kind'] in EXPECT_NONE}

print("=== FAIL 모드 ===")
app, pf = analyze_condition(web, dict(combo, mode='fail'), 'fail')
got = {}
for name, ip in (pf.get('items') or {}).items():
    for d in ip.get('details') or []:
        if d.get('fail_type'):
            got.setdefault(str(d['sample']), []).append((name, d['fail_type']))
print("fail 상세가 붙은 유닛:", len(got), " sample_counts:", pf.get('sample_counts'))
ok = bad = 0
for serial, case in sorted(exp_fail.items()):
    hit = got.get(str(serial), [])
    types = {t for _, t in hit}
    good = types == {EXPECT_FAIL_TYPE[case['kind']]}
    ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
    print("  %s #%-4d %-14s 기대 %-14s 실제 %s" % ('OK ' if good else '**X**', serial,
          case['item'][:14], EXPECT_FAIL_TYPE[case['kind']], hit or '(없음)'))
extra = set(got) - {str(s) for s in exp_fail}
print("  기대 밖 fail 유닛:", sorted(extra, key=lambda x: int(x) if x.isdigit() else 0)[:10],
      "총", len(extra))
print("  → 일치 %d / 불일치 %d" % (ok, bad))

print("\n=== PASS 모드 ===")
app2, pp = analyze_condition(web, dict(combo, mode='pass'), 'pass')
pp = web.payload_with_items(app2, pp, 'pass', 'none')
reason_by = {}
for row in pp.get('selected_summary') or []:
    ip = (pp.get('items') or {}).get(row.get('item_key') or row['item']) or {}
    for d in ip.get('details') or []:
        if d.get('result') == 'SELECT':
            reason_by.setdefault(str(d['sample']), []).append((row['item'], row.get('reason')))
print("SELECT 항목:", len(pp.get('selected_summary') or []), "· SELECT 유닛:", len(reason_by))
ok = bad = 0
for serial, case in sorted(exp_pass.items()):
    hit = reason_by.get(str(serial), [])
    reasons = {r for _, r in hit}
    good = reasons == {EXPECT_PASS_REASON[case['kind']]}
    ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
    print("  %s #%-4d %-14s 기대 %-18s 실제 %s" % ('OK ' if good else '**X**', serial,
          case['item'][:14], EXPECT_PASS_REASON[case['kind']], hit or '(없음)'))
for serial, case in sorted(exp_none.items()):
    hit = reason_by.get(str(serial), [])
    print("  %s #%-4d %-14s 기대 (안 걸림)         실제 %s" % ('OK ' if not hit else '**X**',
          serial, case['item'][:14], hit or '(없음)'))
extra = set(reason_by) - {str(s) for s in exp_pass}
print("  기대 밖 SELECT 유닛 수:", len(extra), sorted(extra, key=lambda x: int(x) if x.isdigit() else 0)[:12])
print("  → 일치 %d / 불일치 %d" % (ok, bad))

print("\n=== 부가 검증 ===")
# 1) 단위 필터(§3-5) — FailStep / mOhm / Binnary 는 분석 항목에서 빠져야 한다
names = {r['item'] for r in pp.get('results') or []}
for bad in ('FT_FAIL_STEP', 'FCLK_MHZ', 'DEVICE_ID'):
    print("  %s 단위 필터로 제외: %s" % ('OK ' if bad not in names else '**X**', bad))
from make_known_data import ITEMS
print("  %s 분석 항목 수 %d (측정 항목 %d개가 정답)" % ("OK " if len(names)==len(ITEMS) else "**X**", len(names), len(ITEMS)))

# 2) DEVICE_ID 공란 유닛 — Pre 매칭 실패분은 분석 모집단에서 빠진다
from make_known_data import NO_PRE_SERIALS
ids = {str(r.get('sample')) for r in app2.post_records['VOUT_2V5']}
gone = {str(x) for x in NO_PRE_SERIALS} & ids
print("  %s DEVICE_ID 공란 유닛 %s 이 분석 모집단에서 제외됨 (모집단 %d)"
      % ('OK ' if not gone else '**X**', NO_PRE_SERIALS, len(ids)))

# 3) Pre↔Post 조인 (§3-3)
ms = pp.get('match_summary')
print("  Pre 매칭: %s (231 중 229 매칭 = DEVICE_ID 공란 2건 제외가 정답)" % ms)

# 4) Marginal(Tail) 게이트 — Tail 3건이 접혀야 한다
fg = (pf.get('fail_gate') or {}).get('items') or {}
folded = sum(v['folded'] for v in fg.values())
want_tail = sum(1 for c in CASES if EXPECT_FAIL_TYPE.get(c['kind']) == 'Tail')
print("  %s Marginal 접힘 %d건 (Tail %d건이 정답)" % ('OK ' if folded == want_tail else '**X**', folded, want_tail))

# 4b) 스펙 대비 게이트 — Marginal(...) 3건만 접혀야 한다
sg = (pp.get('shift_gate') or {}).get('items') or {}
folded_units = set()
for row in pp.get('selected_summary') or []:
    key = row.get('item_key') or row['item']
    if sg.get(key, {}).get('folded'):
        ip = (pp.get('items') or {}).get(key) or {}
        for d in ip.get('details') or []:
            if d.get('result') == 'SELECT':
                folded_units.add(str(d['sample']))
want = {str(c['serial']) for c in CASES if c['kind'] in FOLDED_KINDS}
print("  %s 스펙 대비 기준에서 접히는 유닛 = %s (기대 %s)"
      % ('OK ' if folded_units == want else '**X**',
         sorted(folded_units, key=int), sorted(want, key=int)))

# 5) Hot / Cold 는 깨끗해야 한다
for temp in ('Hot', 'Cold'):
    a2, p2 = analyze_condition(web, dict(combo, ft_temp=temp, mode='fail'), 'fail')
    a3, p3 = analyze_condition(web, dict(combo, ft_temp=temp), 'pass')
    nf = (p2.get('sample_counts') or {}).get('fail')
    ns = len(p3.get('selected_summary') or [])
    print("  %s %-5s  fail 유닛 %s · Abnormal Pass 항목 %s  (둘 다 0이 정답)"
          % ('OK ' if (nf == 0 and ns == 0) else '**X**', temp, nf, ns))

# 6) 168/500hrs — Pre 부터 튀도록 설계한 유닛(Measured 3 + Tail 3)은 여기서도 잡히는 게 정답.
#    나머지(Delta / Measured+Delta / 모든 Fail 유형)는 마지막 회차에만 나타난다.
# Pre 시점부터 이미 집단에서 튀도록 설계한 유닛 — 스트레스 전부터 통계적 이상치라
# 앞 회차에서도 잡히는 게 정답이다. Tail(207~209)·Tail2(186~188)·Measured(216~218)·
# Marginal(Measured)(225)·Tau 경계(197·198).
# 경계 유닛 193(Bnd:Mea+)은 캘리브레이션 결과 임계 바로 위라 앞 회차에서는 안 걸린다.
EARLY_EXPECTED = {'186', '187', '188', '197', '198', '207', '208', '209',
                  '216', '217', '218', '225'}
for ro in ('168hrs', '500hrs'):
    a4, p4 = analyze_condition(web, dict(combo, readout=ro, mode='fail'), 'fail')
    a5, p5 = analyze_condition(web, dict(combo, readout=ro), 'pass')
    p5 = web.payload_with_items(a5, p5, 'pass', 'none')
    units = set()
    for row in p5.get('selected_summary') or []:
        ip = (p5.get('items') or {}).get(row.get('item_key') or row['item']) or {}
        for d in ip.get('details') or []:
            if d.get('result') == 'SELECT':
                units.add(str(d['sample']))
    nf = (p4.get('sample_counts') or {}).get('fail')
    good = (nf == 0 and units == EARLY_EXPECTED)
    print("  %s Room %-7s  fail 유닛 %s (0이 정답) · Abnormal Pass 유닛 %s"
          % ('OK ' if good else '**X**', ro, nf, sorted(units, key=int)))

# 7) 산포 변화 양상 — 회차 단조 증가, 온도 순서 Cold < Room < Hot
import csv as _csv, io as _io2, statistics as _st
from make_known_data import ITEMS as _ITEMS, CASES as _CASES
_ROOT = os.path.join(web.DATA_ROOT, 'KNOWN01', '00_KV1-0_K001_K01')
_CASE_SERIALS = {str(c['serial']) for c in _CASES}


def _sigma(path, col, drop_cases=True):
    rows = list(_csv.reader(_io2.open(path, encoding='utf-8')))
    i = rows[46].index(col)
    vals = [float(r[i]) for r in rows[52:]
            if r[i] and not (drop_cases and r[1] in _CASE_SERIALS)]
    return _st.pstdev(vals)


bad_ro = bad_t = 0
for _it in _ITEMS:
    n = _it['name']
    ro = [_sigma(os.path.join(_ROOT, '01_Post', 'KNOWN01_ER01_AAA_K001_ROOM_HTOL_%s.csv' % x), n)
          for x in ('168hrs', '500hrs', '1000hrs')]
    hot = _sigma(os.path.join(_ROOT, '01_Post', 'KNOWN01_EH01_AAA_K001_HOT_HTOL_1000hrs.csv'), n)
    cold = _sigma(os.path.join(_ROOT, '01_Post', 'KNOWN01_EC01_AAA_K001_COLD_HTOL_1000hrs.csv'), n)
    if not (ro[0] < ro[1] < ro[2]):
        bad_ro += 1
    if not (cold < ro[2] < hot):
        bad_t += 1
print("  %s 산포: 회차 단조 증가 위반 %d / %d 항목" % ('OK ' if not bad_ro else '**X**', bad_ro, len(_ITEMS)))
print("  %s 산포: 온도 순서(Cold < Room < Hot) 위반 %d / %d 항목"
      % ('OK ' if not bad_t else '**X**', bad_t, len(_ITEMS)))
