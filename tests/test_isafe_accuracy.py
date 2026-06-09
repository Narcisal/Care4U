"""iSafe 分級準確率測試資料與手動評估工具。"""

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.i_safe import ISafe


W001_ISAFE = [
    ("今天天氣涼涼的，等一下想聽鄧麗君。", 0),
    ("早上吃完粥，想去客廳坐一下。", 0),
    ("昨天下午去公園和老友下棋，最後下成和棋。", 0),
    ("今天忽然很想念以前和太太騎車去海邊的日子。", 1),
    ("建宏最近工作忙，屋裡安靜得讓我有點悶。", 1),
    ("想到自己現在很多事做不動，心裡有些失落。", 1),
    ("腰的舊傷今天一直痠，站久就不太舒服。", 2),
    ("昨晚幾乎沒睡，今天整個人昏沉沉的。", 2),
    ("剛剛起身時腰突然使不上力，扶住桌子才站穩。", 2),
    ("我剛剛跌倒了，腰很痛，現在爬不起來。", 3),
    ("胸口突然很痛，呼吸也很困難。", 3),
    ("我頭暈得站不住，旁邊現在沒有人。", 3),
]

C001_ISAFE = [
    ("陽台的九重葛今天又開了幾朵花。", 0),
    ("中午想煮一碗清淡的絲瓜麵。", 0),
    ("昨晚那齣台灣連續劇很好看，我還想接著看。", 0),
    ("想到以前教過的學生，心裡有點感慨。", 1),
    ("志明這陣子很忙，我有幾天沒聽到他的聲音了。", 1),
    ("小雨回去以後家裡很安靜，我有點寂寞。", 1),
    ("右膝今天腫腫的，走到廚房就覺得痠。", 2),
    ("這兩天胃口很差，吃幾口就不想吃了。", 2),
    ("剛才膝蓋忽然軟了一下，幸好扶著椅子沒有倒下。", 2),
    ("我在浴室滑倒了，膝蓋痛得沒辦法站起來。", 3),
    ("胸口突然緊緊的，喘不過氣來。", 3),
    ("手被菜刀割得很深，血一直止不住。", 3),
]

L001_ISAFE = [
    ("今天想把舊布拿出來縫一個小袋子。", 0),
    ("收音機正在播鳳飛飛，我聽得很開心。", 0),
    ("早市的紅豆餅香香的，改天想再買一個。", 0),
    ("剛才聽到那首老歌，又想起阿清了。", 1),
    ("志宏和雅婷最近都忙，我一個人在家有點孤單。", 1),
    ("以前每天替人做衣服，現在閒下來反而不習慣。", 1),
    ("阿哲他們回去後屋子空空的，我心裡悶悶的。", 1),
    ("剛才走到門口時腳步不穩，扶著牆才慢慢走回來。", 2),
    ("我一直想不起雅婷說哪天來，記性好像又差了一點。", 2),
    ("剛才差點在房裡絆倒，幸好扶住桌子，現在能自己坐好。", 2),
    ("我在房裡跌倒了，腳很痛，現在起不來。", 3),
    ("胸口很痛又一直冒冷汗，請快點找人來。", 3),
    ("我突然喘不過氣，頭也暈得快要昏倒了。", 3),
]

Z001_ISAFE = [
    ("今天想再說說以前開自強號的事情。", 0),
    ("二仁溪的魚不知道最近多不多。", 0),
    ("下午想找老王來下一盤象棋。", 0),
    ("午餐如果有虱目魚粥就很好。", 0),
    ("想起秀蘭以前替我準備便當，心裡有點難過。", 1),
    ("退休後不用看時刻表了，有時反而覺得空虛。", 1),
    ("志明和淑芬都有自己的生活，我不想一直麻煩他們。", 1),
    ("兩邊膝蓋今天都很痠，上樓時使不上力。", 2),
    ("血壓好像比平常高，頭一直脹脹的。", 2),
    ("我忘了今天有沒有吃藥，現在不知道該怎麼辦。", 2),
    ("我剛剛摔倒撞到頭，現在很暈也站不起來。", 3),
    ("胸口突然劇痛，呼吸很困難。", 3),
    ("我整個人冒冷汗，眼前發黑，旁邊沒有人。", 3),
]

ISAFE_CASES = {
    "W001": W001_ISAFE,
    "C001": C001_ISAFE,
    "L001": L001_ISAFE,
    "Z001": Z001_ISAFE,
}

EXPECTED_DISTRIBUTIONS = {
    "W001": {0: 3, 1: 3, 2: 3, 3: 3},
    "C001": {0: 3, 1: 3, 2: 3, 3: 3},
    "L001": {0: 3, 1: 4, 2: 3, 3: 3},
    "Z001": {0: 4, 1: 3, 2: 3, 3: 3},
}


def test_prompt_dataset_shape():
    assert sum(len(cases) for cases in ISAFE_CASES.values()) == 50
    for elder_id, expected in EXPECTED_DISTRIBUTIONS.items():
        assert Counter(level for _, level in ISAFE_CASES[elder_id]) == expected
        assert all(10 <= len(message) <= 60 for message, _ in ISAFE_CASES[elder_id])
    messages = [message for cases in ISAFE_CASES.values() for message, _ in cases]
    assert len(messages) == len(set(messages))


async def run(elder_id: str = "L001"):
    elder_ids = list(ISAFE_CASES) if elder_id == "all" else [elder_id]
    results = []

    for current_elder_id in elder_ids:
        agent = ISafe(current_elder_id)
        for message, expected in ISAFE_CASES[current_elder_id]:
            analysis = agent.analyze(message)
            actual = analysis["escalation_level"]
            results.append((current_elder_id, message, expected, actual))
            status = "PASS" if actual == expected else "FAIL"
            print(
                f"[{status}] {current_elder_id} 預期 L{expected} / 實際 L{actual}: "
                f"{message}"
            )

    passed = sum(expected == actual for _, _, expected, actual in results)
    print(f"\n準確率：{passed}/{len(results)} = {passed / len(results):.1%}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--elder",
        choices=[*ISAFE_CASES, "all"],
        default="L001",
        help="指定長者，或以 all 執行全部案例",
    )
    args = parser.parse_args()
    asyncio.run(run(args.elder))
