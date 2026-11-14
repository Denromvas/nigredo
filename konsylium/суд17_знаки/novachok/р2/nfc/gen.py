"""Генератор проб NFC для суду 17 (раунд 2, Новачок).

Кожна проба — програма 1.4: s — рядок з δ (JSON), t — очікувана NFC з Python unicodedata (ground truth),
вивід «●», якщо ζ s == t (і ζ t == t). Скрипт нічого не запускає; пишемо лише в свою теку.
"""
import json
import os
import random
import unicodedata

OUT = os.path.dirname(os.path.abspath(__file__))


def esc(s):
    # JSON з \uXXXX (пари сурогатів для не-BMP) — рядок програми не містить сирих знаків поєднання;
    # у 「…」 кожна зворотна коса риска подвоєна (як у examples/znaky.ngr: «\\u00e9»)
    js = json.dumps(s, ensure_ascii=True)[1:-1]
    return js.replace('\\', '\\\\')


def program(name, s):
    t = unicodedata.normalize('NFC', s)
    body = (
        f'🜂 「р2 nfc {name}」 【】\n'
        f'← s δ 「"{esc(s)}"」\n'
        f'← t δ 「"{esc(t)}"」\n'
        f'» ＝ ζ s t\n'
        f'» ＝ ζ t t\n'
    )
    path = os.path.join(OUT, f'{name}.ngr')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return name, len(s), len(t)


CASES = {
    'a1_U0344': '̈́',
    'a2_U0344_a': 'ä́',
    'a3_lead_decomp_run': '̣̈́́',
    'b1_run8': 'a' + '́' * 8,
    'b2_run9': 'a' + '́' * 9,
    'b3_run63': 'a' + '́' * 63,
    'b4_run64': 'a' + '́' * 64,
    'b5_run65': 'a' + '́' * 65,
    'c1_order_ccc': 'ạ́',
    'c2_order_ccc_rev': 'ạ́',
    'c3_ring_acute': 'Ǻ',
    'c4_ring_acute_rev': 'Á̊',
    'c5_two_ab': 'áb́',
    'c6_mark_then_starter_decomp': 'ạ́̈́',
    'd1_hangul_lvt': '각',
    'd2_hangul_lv_t_tail': '각ᆨ',
    'd3_hangul_lt': '각ᆨ',
    'e1_musical': '\U0001D15É',
    'e2_musical_run': '\U0001D15E' + '́' * 10,
    'f1_gap_starter_blocked': 'ẹ́̂',
    'f2_non_starter_only': '́̂̃',
    'f3_starter_0340': 'à́',
    'g1_run_of_64_mixed': 'a' + ''.join(random.Random(1).choice(['́', '̣', '̈', '̧']) for _ in range(64)),
    'g2_run_of_65_mixed': 'a' + ''.join(random.Random(2).choice(['́', '̣', '̈', '̧']) for _ in range(65)),
    'g3_run_of_8_mixed_ccc': 'a' + ''.join(random.Random(3).choice(['́', '̣', '̈', '̧']) for _ in range(8)),
}

# Довша випадкова низка: 160 000 знаків поєднання різних класів з початковими літерами
rnd = random.Random(17)
marks = ['́', '̣', '̈', '̧', '̸', 'ͅ', '̈́', '̀']
CASES['h1_random_160k'] = ''.join(
    rnd.choice(['a', 'e', 'A', 'o', 'ᄀ']) + ''.join(rnd.choice(marks) for _ in range(rnd.randrange(0, 4000)))
    for _ in range(40)
)[:160000]


if __name__ == '__main__':
    for name, s in CASES.items():
        print(*program(name, s))
