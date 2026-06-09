"""RAG 記憶召回測試資料與手動評估工具。"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from backend.memory.vector_store import VectorMemoryStore


W001_RAG = [
    ("我以前是做什麼工作的？", ["電腦", "工程師"]),
    ("我的工作經歷見證了台灣哪個產業的發展？", ["台灣", "電腦產業"]),
    ("哪些事情最容易讓我想起過世的妻子？", ["妻子", "唱歌"]),
    ("我最喜歡鄧麗君的哪一首歌？", ["鄧麗君", "月亮代表我的心"]),
    ("年輕時我常騎什麼車帶妻子出去兜風？", ["重機", "兜風"]),
    ("退休後我常去哪裡找老友下棋？", ["公園", "象棋"]),
    ("我一直想回哪個老家走走？", ["苗栗", "老家"]),
    ("小玲、建宏和安安分別是我的什麼人？", ["小玲", "建宏", "安安"]),
    ("我的腰為什麼常常不舒服？", ["腰", "舊傷"]),
]

C001_RAG = [
    ("我退休以前在哪裡工作？", ["國小", "老師"]),
    ("我退休後為什麼還會夢到以前的教室？", ["教書", "學生"]),
    ("陽台上我種了哪些花？", ["茉莉", "蘭花", "吊蘭"]),
    ("孩子們回家時最惦記我煮的哪道菜？", ["滷肉", "老滷汁"]),
    ("我常和哪位老鄰居一起去市場？", ["美月姐", "市場"]),
    ("志明是我的什麼人？", ["志明", "兒子"]),
    ("小雨回來時最想吃什麼？", ["小雨", "滷肉"]),
    ("什麼情況下我的膝蓋比較容易痛？", ["膝蓋", "走遠", "樓梯"]),
    ("我每天晚上最喜歡看哪一類節目？", ["台灣劇", "連續劇"]),
]

L001_RAG = [
    ("我以前靠什麼手藝工作？", ["裁縫", "衣服"]),
    ("我做的哪一種衣服最出名？", ["旗袍", "裁縫"]),
    ("第一台縫紉機是誰送給我的？", ["阿清", "縫紉機"]),
    ("我最喜歡聽哪位歌手的老歌？", ["鳳飛飛", "老歌"]),
    ("我帶阿哲去市場時常買什麼點心？", ["阿哲", "紅豆餅"]),
    ("志宏是我的什麼人？", ["志宏", "兒子"]),
    ("雅婷小時候常在旁邊看我做什麼？", ["雅婷", "縫衣服"]),
    ("佳穎來陪我時會放誰的歌？", ["佳穎", "鳳飛飛"]),
    ("市場的魚販阿伯看到我會怎麼招呼？", ["魚販阿伯", "月琴姊"]),
]

Z001_RAG = [
    ("我開自強號時最重視的是什麼？", ["自強號", "準點"]),
    ("我剛進鐵路局時開過哪一種老火車？", ["蒸汽火車", "鐵路"]),
    ("以前我最喜歡去哪裡釣魚？", ["二仁溪", "釣魚"]),
    ("秀蘭以前是我的什麼人？", ["秀蘭", "太太"]),
    ("我在台南最惦記哪一道早餐？", ["虱目魚", "台南"]),
    ("我常找誰一起下象棋？", ["老王", "象棋"]),
    ("志明和淑芬是我的什麼人？", ["志明", "淑芬"]),
    ("小宇為什麼把我當成偶像？", ["小宇", "火車"]),
]

RAG_CASES = {
    "W001": W001_RAG,
    "C001": C001_RAG,
    "L001": L001_RAG,
    "Z001": Z001_RAG,
}


def test_prompt_dataset_shape():
    assert {elder_id: len(cases) for elder_id, cases in RAG_CASES.items()} == {
        "W001": 9,
        "C001": 9,
        "L001": 9,
        "Z001": 8,
    }
    assert sum(len(cases) for cases in RAG_CASES.values()) == 35
    assert all(
        2 <= len(keywords) <= 3
        for cases in RAG_CASES.values()
        for _, keywords in cases
    )
    questions = [question for cases in RAG_CASES.values() for question, _ in cases]
    assert len(questions) == len(set(questions))


async def run(elder_id: str = "L001"):
    elder_ids = list(RAG_CASES) if elder_id == "all" else [elder_id]
    results = []

    for current_elder_id in elder_ids:
        store = VectorMemoryStore()
        for question, keywords in RAG_CASES[current_elder_id]:
            memories = store.search_similar_memories(
                current_elder_id,
                [],
                limit=5,
                query_text=question,
            )
            text = " ".join(str(memory) for memory in memories)
            matched = [keyword for keyword in keywords if keyword in text]
            passed = bool(matched)
            results.append((current_elder_id, question, keywords, matched, passed))
            status = "PASS" if passed else "FAIL"
            print(
                f"[{status}] {current_elder_id} {question} "
                f"命中：{matched or '無'} / 關鍵字：{keywords}"
            )

    passed_count = sum(result[-1] for result in results)
    print(
        f"\n召回率：{passed_count}/{len(results)} = "
        f"{passed_count / len(results):.1%}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--elder",
        choices=[*RAG_CASES, "all"],
        default="L001",
        help="指定長者，或以 all 執行全部案例",
    )
    args = parser.parse_args()
    asyncio.run(run(args.elder))
