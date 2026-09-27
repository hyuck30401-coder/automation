# -*- coding: utf-8 -*-
"""경계 케이스를 Grubbs 임계 바로 옆에 앉힌다.

수렴 조건은 "목표 비율에 딱 맞추기"가 아니라 **임계선을 확실히 갈라 타되 가깝게**다.
이상치 자신이 표본 sigma 를 부풀리는 되먹임이 있어(주입량을 키우면 임계도 같이 밀린다)
±4% 같은 좁은 목표에는 안정적으로 수렴하지 않는다. 판정이 갈리는 것은 임계선의 어느
쪽이냐이므로, 양쪽 여유 1~15% 안에 들어오면 경계 검증으로 충분하다.

Mea_S / Diff_S 는 표본 sigma 에 의존하므로 "z 를 4.2 로 넣으면 4.2 가 나온다"가
성립하지 않는다(이상치 자신이 sigma 를 부풀린다). 그래서 생성 -> 실제 통계량 측정 ->
주입량 보정 -> 재생성 을 반복해 목표 비율(통계량 / 임계값)에 수렴시킨다.
결과는 tools/known_data_calib.json 에 남고, make_known_data.py 가 그걸 읽는다.
"""
import io, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, '_automation'))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
CALIB = os.path.join(HERE, 'known_data_calib.json')

# 역할 -> (분석 모드, 보는 축, 목표 비율 = 통계량/임계값)
TARGETS = {
    'Bnd:Slight+': ('fail', 'diff', 1.04),
    'Bnd:Slight-': ('fail', 'diff', 0.96),
    'Bnd:Mea+':    ('pass', 'mea',  1.04),
    'Bnd:Mea-':    ('pass', 'mea',  0.96),
    'Bnd:Delta+':  ('pass', 'diff', 1.04),
    'Bnd:Delta-':  ('pass', 'diff', 0.96),
}


def regenerate():
    subprocess.run([sys.executable, os.path.join(HERE, 'make_known_data.py')],
                   check=True, capture_output=True)


def measure():
    global cases
    """각 경계 케이스의 (통계량 / 임계값) 실측치."""
    for mod in ('make_known_data', 'cdf_compare_web', '_regression_lib', 'headless'):
        sys.modules.pop(mod, None)
    import headless, cdf_compare_web as web           # noqa: F401
    from make_known_data import CASES, DEVICE, FOLDER
    from _regression_lib import analyze_condition
    web.DATA_ROOT = os.path.abspath('Known Data')
    combo = {'device': DEVICE, 'ver': 'KV1-0', 'lot': 'K001', 'purpose': 'K01',
             'folder': FOLDER, 'item': 'HTOL', 'readout': '1000hrs', 'ft_temp': 'Room'}
    globals()['cases'] = cases = {c['kind']: c for c in CASES if c['kind'] in TARGETS}
    got = {}
    for mode in ('pass', 'fail'):
        app, payload = analyze_condition(web, dict(combo, mode=mode), mode)
        if mode == 'fail':
            # fail 분석은 app.post_records 를 비워두므로 item_analysis 를 못 쓴다.
            # payload 의 항목별 상세에서 직접 읽는다.
            items = payload.get('items') or {}
        for kind, case in cases.items():
            if TARGETS[kind][0] != mode:
                continue
            axis = TARGETS[kind][1]
            if mode == 'fail':
                ip = items.get(case['item']) or {}
                details = ip.get('details') or []
                thr = ip.get('mea_threshold' if axis == 'mea' else 'diff_threshold')
            else:
                entry = web.item_analysis(app, case['item'])
                details = entry['details']
                rr = entry.get('result_row') or {}
                thr = rr.get('mea_threshold' if axis == 'mea' else 'diff_threshold')
            hit = [d for d in details if str(d.get('sample')) == str(case['serial'])]
            if not hit or not thr:
                continue
            stat = hit[0].get('mea_s' if axis == 'mea' else 'diff_s')
            if stat is None:
                continue
            got[kind] = (abs(stat) / thr, abs(stat), thr, hit[0].get('diff'))
    return got


def main():
    calib = {}
    if os.path.exists(CALIB):
        with io.open(CALIB, encoding='utf-8') as fh:
            calib = json.load(fh)
    for step in range(1, 41):
        regenerate()
        got = measure()
        from make_known_data import TUNE
        pending, report = {}, []
        for kind, (mode, axis, target) in TARGETS.items():
            if kind not in got:
                report.append('%s=측정실패' % kind)
                pending[kind] = None
                continue
            ratio = got[kind][0]
            report.append('%s=%.3f' % (kind.replace('Bnd:', ''), ratio))
            side_ok = (ratio > 1.0) if target > 1.0 else (ratio < 1.0)
            near_ok = 0.01 <= abs(ratio - 1.0) <= 0.15
            if side_ok and near_ok:
                continue
            pre_z, post_z = TUNE[kind]
            if kind.startswith('Bnd:Slight'):
                # post 는 스펙이 고정한다 -> pre 위치를 움직여 이동량(=Diff_S)을 맞춘다.
                # diff 는 pre_z 에 대해 거의 선형이라 해석적으로 한 번에 푼다.
                from make_known_data import ITEMS as _I
                it = next(x for x in _I if x['name'] == cases[kind]['item'])
                rel = it['sigma'] / abs(it['mu'])
                diff = got[kind][3]
                if diff is None:
                    continue
                dm = it['drift_mu']
                want = dm + (diff - dm) * (target * got[kind][2] / got[kind][1])
                new_pre = pre_z + (diff - want) / rel * 0.5      # 감쇠 0.5
                pending[kind] = [round(max(0.0, min(new_pre, 5.99)), 5), 0.0]
                continue
            span = post_z - pre_z if abs(post_z - pre_z) > 1e-9 else post_z
            scale = 1.0 + 0.5 * (target / ratio - 1.0)   # 감쇠 — 되먹임이 있어 과잉보정 방지
            new_post = (pre_z + span * scale) if abs(post_z - pre_z) > 1e-9 else post_z * scale
            pending[kind] = [round(new_post, 5), round(new_post, 5)] \
                if kind.startswith('Bnd:Mea') else round(new_post, 5)
        print('  [%2d] %s' % (step, '  '.join(sorted(report))))
        if not pending:
            # 지금 디스크에 있는 파일이 바로 이 측정 결과다 — 여기서 멈춰야 한다.
            print('  수렴 (%d회)' % step)
            break
        calib.update({k: v for k, v in pending.items() if v is not None})
        with io.open(CALIB, 'w', encoding='utf-8') as fh:
            json.dump(calib, fh, ensure_ascii=False, indent=2)
    print('\n최종 (통계량 / 임계값):')
    for kind, (ratio, stat, thr, _d) in sorted(measure().items()):
        mark = 'SELECT' if ratio > 1 else '  OK  '
        print('  %-14s %.3f  %s   (통계량 %.3f · 임계 %.3f)' % (kind, ratio, mark, stat, thr))


if __name__ == '__main__':
    main()
