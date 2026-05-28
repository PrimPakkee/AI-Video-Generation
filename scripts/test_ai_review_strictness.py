#!/usr/bin/env python3
"""
AI Review Strictness Testing Script - v0.4.6.9

Tests the strict scoring calibration logic to ensure:
1. Broken prompts get appropriately low scores
2. Hard caps are applied correctly
3. Quality flags are detected properly
4. Score-comment consistency calibration works

Usage:
    python scripts/test_ai_review_strictness.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.llm_topic_enhancer import LLMTopicEnhancer


# Test prompts
TEST_PROMPTS = {
    "broken_title": """
## Title
Wh

## Topic
Interesting mathematical puzzle about probability

## Target Platform
TikTok / YouTube Shorts / Instagram Reels

## Target Audience
Students, parents, math enthusiasts

## Video Length
50-60 seconds

## Core Concept
Understanding basic probability through a simple game

## Puzzle Setup
There is a game with two doors. One has a prize, one is empty.

## Question
Which door should you choose?

## Correct Answer
Either door has 50% chance initially.

## Reasoning Steps
1. Two doors, one prize
2. Equal probability for each
3. Random choice is fine

## Visual Style
Clean white background, hand-drawn illustrations, simple diagrams

## On-screen Text
Show doors, probability percentages

## Format Requirements
- Single narrator monologue
- No dialogue or podcast format
- 50-60 second pacing
- Clear hook and ending

## Constraints
- Do not alter the puzzle conditions
- Answer must be mathematically correct
- Visuals must support reasoning
""",

    "missing_answer": """
## Title
The Two-Door Probability Puzzle

## Topic
Understanding probability through door selection game

## Target Platform
TikTok / YouTube Shorts / Instagram Reels

## Target Audience
Students, parents, math enthusiasts

## Video Length
50-60 seconds

## Core Concept
Basic probability calculation in a two-door game

## Puzzle Setup
There is a game with two doors. One has a prize behind it, one is empty. You must choose one door.

## Question
Which door should you choose to maximize your chance of winning?

## Reasoning Steps
1. There are two doors
2. One has a prize
3. Equal probability means either choice is valid
4. Random selection is acceptable

## Visual Style
Clean white background, hand-drawn illustrations of two doors, simple probability diagram showing 50/50

## On-screen Text
Display door numbers, show probability fractions

## Format Requirements
- Single narrator monologue
- No dialogue or interview format
- 50-60 second short video pacing
- Strong opening hook
- Clear ending with takeaway

## Constraints
- Do not change the number of doors
- Answer must be mathematically accurate
- Visuals must clearly show two doors
- No decorative or irrelevant scenes
""",

    "generic_prompt": """
## Title
Educational Math Video

## Topic
Math concept explanation

## Target Platform
Short video platforms

## Target Audience
General viewers

## Video Length
Short format

## Core Concept
Educational content

## Puzzle Setup
There is a problem to solve.

## Question
What is the solution?

## Correct Answer
The solution is provided.

## Reasoning Steps
1. Understand the problem
2. Apply the method
3. Get the answer

## Visual Style
Clean background, simple graphics

## On-screen Text
Show relevant information

## Format Requirements
- Clear narration
- Appropriate pacing
- Good structure

## Constraints
- Accurate content
- Clear explanation
""",

    "strong_prompt": """
## Title
The Monty Hall Paradox: Why Switching Doors Wins

## Topic
Counterintuitive probability in the Monty Hall game - understanding why switching doors after a reveal gives you 2/3 chance instead of 1/2

## Target Platform
TikTok / YouTube Shorts / Instagram Reels

## Target Audience
Students, parents, math enthusiasts, puzzle lovers

## Video Length
50-60 seconds

## Core Concept
Conditional probability: how revealing information changes the probability landscape, demonstrating why intuition fails in the Monty Hall problem

## Puzzle Setup
You're on a game show. There are 3 doors: one has a car (prize), two have goats. You pick Door 1. The host (who knows what's behind each door) opens Door 3, revealing a goat. Now the host asks: "Do you want to switch to Door 2, or stay with Door 1?"

## Question
Should you switch to Door 2, or stay with Door 1? And what is your winning probability for each choice?

## Correct Answer
You should switch to Door 2. Switching gives you a 2/3 (66.7%) chance of winning the car, while staying gives only 1/3 (33.3%) chance.

## Reasoning Steps
1. When you first pick Door 1, it has a 1/3 chance of being correct. The other two doors together have a 2/3 chance.
2. The host knows where the car is and deliberately opens a door with a goat (Door 3). This is not random.
3. The host's reveal concentrates the 2/3 probability onto Door 2, because if the car were behind Door 2 or Door 3, the host would be forced to show the goat in one of them.
4. If you picked wrong initially (2/3 chance), switching wins. If you picked right initially (1/3 chance), switching loses.
5. Therefore, switching wins 2/3 of the time.

## Visual Direction
- **Core diagram**: Three doors labeled 1, 2, 3. Use simple hand-drawn rectangles with bold labels.
- **Scene 1 (0:00-0:08)**: Show all three closed doors. Highlight Door 1 when picked. Text: "You pick Door 1. 1/3 chance."
- **Scene 2 (0:08-0:18)**: Door 3 opens, revealing a goat icon. Text: "Host opens Door 3. Always a goat."
- **Scene 3 (0:18-0:28)**: Animate splitting probability: show 1/3 arrow staying on Door 1, and 2/3 arrow moving to Door 2. Text: "Switch = 2/3 chance."
- **Scene 4 (0:28-0:42)**: Show two parallel timelines: "Stay" path (loses) and "Switch" path (wins). Use checkmark and X.
- **Scene 5 (0:42-0:52)**: Summarize with large "2/3" text over Door 2.
- **Scene 6 (0:52-0:58)**: Closing text: "Always switch. Math > intuition."
- **Constraints**: No decorative backgrounds. No additional objects. White background only. Hand-drawn style throughout. Maintain visual consistency across all scenes.

## On-screen Text / Subtitles
1. "3 doors. 1 car. 2 goats. You pick Door 1." (0:00-0:06)
2. "Host opens Door 3... always a goat." (0:06-0:12)
3. "Should you switch to Door 2?" (0:12-0:16)
4. "Your first pick: only 1/3 chance." (0:16-0:22)
5. "The other two doors: 2/3 chance together." (0:22-0:28)
6. "Host's reveal moves that 2/3 to Door 2." (0:28-0:36)
7. "Switch wins 2 out of 3 times!" (0:36-0:44)
8. "Stay with Door 1? Only 1/3 chance." (0:44-0:50)
9. "Monty Hall: Always switch." (0:50-0:58)

## Narration Script (110-150 words, English)
"You're on a game show. Three doors: one car, two goats. You pick Door 1. The host opens Door 3, revealing a goat. Should you switch to Door 2? Most people say it doesn't matter—fifty-fifty, right? Wrong. Here's why: when you first picked Door 1, it had a one-in-three chance. The other two doors had a two-thirds chance combined. The host knows where the car is and always reveals a goat. That reveal doesn't change your original pick's odds, but it concentrates the two-thirds probability onto the remaining door. If you switch, you win two-thirds of the time. If you stay, you win only one-third. The math is clear: always switch. Your intuition is wrong, and that's the beauty of probability."

## Format Requirements
- Single narrator monologue narration
- No dialogue between multiple speakers
- No interview format
- No podcast-style discussion
- No "Host A and Host B" conversation
- Duration: 50-60 seconds
- Hook: Start with the door choice scenario immediately
- Pacing: Reveal the counterintuitive answer within first 20 seconds, then explain why

## Constraints and Error Prevention
- Do NOT change the number of doors to 2 or 4. Must be exactly 3 doors.
- Do NOT say "the chances are 50/50 after the reveal" — this is the wrong answer.
- The correct answer is "switch gives 2/3, stay gives 1/3" — do not alter this.
- The host MUST know where the car is and MUST always reveal a goat. This is critical to the logic.
- Visual diagram must show probability split: 1/3 stays on Door 1, 2/3 moves to Door 2.
- Do NOT add extra doors, extra goats, or change the rules mid-explanation.
- Do NOT use decorative backgrounds, animated characters, or off-topic visuals.
- All reasoning steps must be mathematically sound and clearly explained.
"""
}


def test_quality_flags():
    """Test that quality flags are detected correctly"""
    print("\n" + "=" * 80)
    print("Testing Quality Flag Detection")
    print("=" * 80)

    enhancer = LLMTopicEnhancer()

    for test_name, prompt in TEST_PROMPTS.items():
        print(f"\n--- Test: {test_name} ---")
        flags = enhancer.analyze_prompt_quality_flags(prompt)

        flagged_issues = [k for k, v in flags.items() if v]
        if flagged_issues:
            print(f"✓ Flags detected: {', '.join(flagged_issues)}")
        else:
            print("✓ No flags detected")

        # Assertions for specific tests
        if test_name == "broken_title":
            assert flags["title_missing_or_too_short"], "Should detect broken title"
            print("  ✓ Correctly detected broken title")

        if test_name == "missing_answer":
            assert flags["no_correct_answer"], "Should detect missing answer"
            print("  ✓ Correctly detected missing answer")

        if test_name == "generic_prompt":
            assert flags["too_generic"], "Should detect generic content"
            print("  ✓ Correctly detected generic content")

        if test_name == "strong_prompt":
            # Strong prompt should have minimal flags
            severe_flags = sum([
                flags.get("title_missing_or_too_short", False),
                flags.get("no_correct_answer", False),
                flags.get("no_clear_question", False),
                flags.get("no_reasoning_steps", False)
            ])
            assert severe_flags == 0, "Strong prompt should not have severe flags"
            print("  ✓ No severe flags (as expected)")

    print("\n✅ All quality flag tests passed!")


def test_hard_caps():
    """Test that hard caps are applied correctly"""
    print("\n" + "=" * 80)
    print("Testing Hard Caps Application")
    print("=" * 80)

    enhancer = LLMTopicEnhancer()

    # Create mock review data with high scores
    mock_high_score_review = {
        "rows": [
            {"criterion": "Completeness", "weight": "15%", "max_score": 15, "score": 14, "llm_score": "14/15", "llm_comment": "Strong", "evaluation_focus": "..."},
            {"criterion": "Logical Correctness", "weight": "20%", "max_score": 20, "score": 18, "llm_score": "18/20", "llm_comment": "Good", "evaluation_focus": "..."},
            {"criterion": "NotebookLM Usability", "weight": "15%", "max_score": 15, "score": 13, "llm_score": "13/15", "llm_comment": "Usable", "evaluation_focus": "..."},
            {"criterion": "Visual Directability", "weight": "10%", "max_score": 10, "score": 9, "llm_score": "9/10", "llm_comment": "Clear", "evaluation_focus": "..."},
            {"criterion": "Short-video Suitability", "weight": "10%", "max_score": 10, "score": 9, "llm_score": "9/10", "llm_comment": "Good", "evaluation_focus": "..."},
            {"criterion": "Single-narrator Compliance", "weight": "10%", "max_score": 10, "score": 10, "llm_score": "10/10", "llm_comment": "Perfect", "evaluation_focus": "..."},
            {"criterion": "Educational Clarity", "weight": "10%", "max_score": 10, "score": 9, "llm_score": "9/10", "llm_comment": "Clear", "evaluation_focus": "..."},
            {"criterion": "Risk & Error Control", "weight": "10%", "max_score": 10, "score": 9, "llm_score": "9/10", "llm_comment": "Good", "evaluation_focus": "..."}
        ],
        "total_score": 91,
        "overall_review": "Excellent prompt"
    }

    # Test 1: broken_title should cap total to 72
    print("\n--- Test: Broken Title Cap ---")
    flags_broken_title = enhancer.analyze_prompt_quality_flags(TEST_PROMPTS["broken_title"])
    capped_review = enhancer.apply_strict_score_caps(mock_high_score_review.copy(), flags_broken_title)
    assert capped_review["total_score"] <= 72, f"Total score should be capped to 72, got {capped_review['total_score']}"
    print(f"✓ Total score capped: {91} → {capped_review['total_score']} (expected ≤ 72)")

    # Test 2: missing_answer should cap total to 65
    print("\n--- Test: Missing Answer Cap ---")
    flags_missing_answer = enhancer.analyze_prompt_quality_flags(TEST_PROMPTS["missing_answer"])
    capped_review = enhancer.apply_strict_score_caps(mock_high_score_review.copy(), flags_missing_answer)
    assert capped_review["total_score"] <= 65, f"Total score should be capped to 65, got {capped_review['total_score']}"
    print(f"✓ Total score capped: {91} → {capped_review['total_score']} (expected ≤ 65)")

    # Test 3: generic_prompt should cap total to 82
    print("\n--- Test: Generic Content Cap ---")
    flags_generic = enhancer.analyze_prompt_quality_flags(TEST_PROMPTS["generic_prompt"])
    capped_review = enhancer.apply_strict_score_caps(mock_high_score_review.copy(), flags_generic)
    assert capped_review["total_score"] <= 82, f"Total score should be capped to 82, got {capped_review['total_score']}"
    print(f"✓ Total score capped: {91} → {capped_review['total_score']} (expected ≤ 82)")

    print("\n✅ All hard cap tests passed!")


def test_consistency_calibration():
    """Test score-comment consistency calibration"""
    print("\n" + "=" * 80)
    print("Testing Score-Comment Consistency Calibration")
    print("=" * 80)

    enhancer = LLMTopicEnhancer()

    # Mock review with high scores but negative comments
    mock_inconsistent_review = {
        "rows": [
            {"criterion": "Completeness", "weight": "15%", "max_score": 15, "score": 14, "llm_score": "14/15", "llm_comment": "The prompt is strong. However, the title is missing some details.", "evaluation_focus": "..."},
            {"criterion": "Logical Correctness", "weight": "20%", "max_score": 20, "score": 19, "llm_score": "19/20", "llm_comment": "Logic is good but the reasoning is somewhat unclear.", "evaluation_focus": "..."},
            {"criterion": "NotebookLM Usability", "weight": "15%", "max_score": 15, "score": 14, "llm_score": "14/15", "llm_comment": "Mostly usable. Some sections are incomplete.", "evaluation_focus": "..."},
            {"criterion": "Visual Directability", "weight": "10%", "max_score": 10, "score": 10, "llm_score": "10/10", "llm_comment": "Visual plan is missing concrete scene details.", "evaluation_focus": "..."},
            {"criterion": "Short-video Suitability", "weight": "10%", "max_score": 10, "score": 9, "llm_score": "9/10", "llm_comment": "Good pacing. Could improve hook.", "evaluation_focus": "..."},
            {"criterion": "Single-narrator Compliance", "weight": "10%", "max_score": 10, "score": 10, "llm_score": "10/10", "llm_comment": "Perfect", "evaluation_focus": "..."},
            {"criterion": "Educational Clarity", "weight": "10%", "max_score": 10, "score": 10, "llm_score": "10/10", "llm_comment": "Clear explanation. Minor gap in examples.", "evaluation_focus": "..."},
            {"criterion": "Risk & Error Control", "weight": "10%", "max_score": 10, "score": 9, "llm_score": "9/10", "llm_comment": "Good safeguards. Lacks explicit constraint on answer accuracy.", "evaluation_focus": "..."}
        ],
        "total_score": 95,
        "overall_review": "Excellent"
    }

    calibrated = enhancer.calibrate_score_comment_consistency(mock_inconsistent_review)

    # Check that scores with negative words have been reduced
    for row in calibrated["rows"]:
        comment = row["llm_comment"].lower()
        has_negative = any(word in comment for word in ["however", "missing", "unclear", "incomplete", "minor gap", "could improve", "lacks"])

        if has_negative:
            # Should have calibration note or reduced score
            assert "calibrated downward" in row["llm_comment"] or row["score"] < row["max_score"], \
                f"{row['criterion']}: comment has negative words but score not calibrated"
            print(f"✓ {row['criterion']}: Score calibrated (negative words detected)")

    print(f"\n✓ Total score after calibration: {mock_inconsistent_review['total_score']} → {calibrated['total_score']}")
    assert calibrated["total_score"] < 95, "Total score should be reduced due to calibration"

    print("\n✅ Consistency calibration tests passed!")


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("AI Review Strictness Testing Suite - v0.4.6.9")
    print("=" * 80)

    try:
        test_quality_flags()
        test_hard_caps()
        test_consistency_calibration()

        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED")
        print("=" * 80)
        print("\nThe strict scoring calibration logic is working correctly:")
        print("  ✓ Quality flags are detected properly")
        print("  ✓ Hard caps are applied as expected")
        print("  ✓ Score-comment consistency calibration works")
        print("\nYou can now test with real LLM calls using:")
        print("  python scripts/test_ai_review_strictness.py --live")
        print("=" * 80)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
