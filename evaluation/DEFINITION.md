# Commitment Definition -- Formal Specification for Evaluation

> This document defines what counts as a commitment in the context of call
> transcript analysis. It is the authoritative reference for human annotators
> creating ground truth data and for evaluating system extraction quality.

---

## 1. What IS a Commitment

A **commitment** is a speech act where a **specific person** explicitly agrees
or promises to **perform a specific action** for or directed at **someone**.

### Required elements (all three must be present):

| Element    | Description                                          | Example                            |
|------------|------------------------------------------------------|------------------------------------|
| **WHO**    | A specific individual (not "we", not "someone")      | "Я", "SPEAKER_ME", "Елена"        |
| **WHAT**   | A concrete, actionable deliverable or task            | "отправлю контракт", "send report" |
| **TO WHOM**| An identifiable recipient (explicit or contextual)    | "тебе", "SPEAKER_OTHER_1", "вам"  |

### Qualifying patterns:

**Strong commitments (confidence >= 0.85):**
- "I will / I'll [verb]" -- "I'll send you the revised proposal"
- "Я сделаю / отправлю / подготовлю" (Russian perfective future) -- "Я отправлю тебе контракт до конца дня"
- "Беру на себя / берусь" -- "Беру на себя подготовку презентации"
- "Давай я займусь" -- "Давай я займусь этим вопросом"
- "Leave it with me / I'll handle that" -- "Leave it with me, I'll get it done"
- Explicit agreement after request: "Можешь прислать?" -> "Да, конечно, пришлю"

**Medium commitments (confidence 0.50 -- 0.84):**
- "I'll try to / I plan to" -- "I'll try to get this done by Friday"
- "Постараюсь / планирую" -- "Постараюсь подготовить к среде"
- "Я буду делать" (Russian imperfective future) -- "Буду работать над этим"
- "I should be able to" -- "I should be able to send it tomorrow"

**Weak commitments (confidence 0.25 -- 0.49, still extracted but flagged):**
- "Может быть я / если получится" -- "Если получится, посмотрю"
- "I might / maybe I'll" -- "Maybe I'll look into that"
- "Я подумаю" -- only if context shows genuine intent to act

---

## 2. What is NOT a Commitment

### Do NOT extract:

| Pattern                                      | Why it fails                           | Example                                           |
|----------------------------------------------|----------------------------------------|---------------------------------------------------|
| General intentions without specific owner     | No WHO                                 | "Нам нужно это обсудить", "We should look into it"|
| Collective statements without assignee        | No specific WHO                        | "Мы должны подготовить", "We need to do X"        |
| Past actions already completed                | Not a future obligation                | "Я уже отправил вчера", "I sent it yesterday"     |
| Questions or requests (without agreement)     | Request != commitment                  | "Можешь прислать?", "Could you send it?"          |
| Hypotheticals without acceptance              | No agreement to act                    | "Если бы мне дали время, я бы мог..."             |
| Meeting agenda topics without conclusion      | Discussion != obligation               | "Давайте обсудим бюджет", "Let's discuss budget"  |
| Statements about third parties not present    | Cannot verify, no recipient in call    | "Маша должна сделать" (Маша not on the call)      |
| Vague expressions of intent                   | No specific WHAT                       | "Надо бы как-нибудь собраться"                     |
| Descriptions of ongoing work                  | Status update, not new commitment      | "Я сейчас над этим работаю"                        |

---

## 3. Edge Cases

### 3.1 Russian Perfective vs Imperfective

| Form        | Verb example      | Classification       | Confidence adjust |
|-------------|-------------------|----------------------|-------------------|
| Perfective  | "сделаю"          | Commitment (strong)  | +0.15 boost       |
| Imperfective| "буду делать"     | Commitment (medium)  | baseline          |
| "постараюсь"| "постараюсь"      | Commitment (weak)    | 0.30-0.40         |

### 3.2 Conditional Promises

"Если ты пришлешь мне данные, я подготовлю презентацию к пятнице."

- **IS** a commitment: specific WHO (I), specific WHAT (prepare presentation),
  specific deadline (Friday), specific condition.
- Mark as `conditional: true`, extract `condition_text`.
- The commitment is real -- it just has a precondition.

### 3.3 Delegated Tasks

"Я попрошу Машу прислать тебе отчет."

- **IS** an outgoing commitment from SPEAKER (they committed to arranging it).
- The WHAT is "arrange for Masha to send the report", not the report itself.
- Direction: outgoing (SPEAKER_ME promised to do the delegating).

### 3.4 Agreement by Confirmation

"-- Можешь посмотреть этот документ?" / "-- Да, конечно."

- **IS** a commitment. The "Да, конечно" in response to a request
  constitutes acceptance and a promise to act.
- WHO: the person who said "Да, конечно"
- WHAT: review the document

### 3.5 Repeated Statements

"Я отправлю тебе контракт. <...several exchanges...> Да, так что контракт я тебе отправлю."

- Extract **once**. Same commitment restated = single entry.
- Use the most complete/clear formulation as the verbatim quote.

### 3.6 Group Meetings with "I'll"

"Хорошо, значит я возьму на себя дизайн, а ты -- разработку."

- **TWO** commitments: one outgoing (design), one incoming (development).
- Each has a specific WHO and specific WHAT.

### 3.7 Soft Hedges That Are Still Commitments

"Ну, я постараюсь к пятнице сделать, но не обещаю."

- **IS** a commitment, but weak (confidence 0.30-0.40).
- The speaker explicitly hedged, so mark `uncertain: true`.

### 3.8 Third-Party Commitments

"Андрей сказал что он подготовит документы к понедельнику."

- If Андрей is on the call: potential incoming commitment.
- If Андрей is NOT on the call: **NOT** extracted (cannot be verified).
- Direction: `third_party` only if neither WHO nor TO_WHOM is SPEAKER_ME.

---

## 4. Direction Classification

| Scenario                                  | Direction      |
|-------------------------------------------|----------------|
| SPEAKER_ME promises to do something        | `outgoing`     |
| Someone promises SPEAKER_ME something      | `incoming`     |
| Two others make promises to each other     | `third_party`  |

---

## 5. Field Definitions for Evaluation

Each commitment in ground truth and predictions has these fields:

| Field          | Type     | Required | Description                                              |
|----------------|----------|----------|----------------------------------------------------------|
| `who`          | string   | Yes      | Speaker label or name of the person making the commitment |
| `to_whom`      | string   | Yes      | Speaker label or name of the recipient                    |
| `text`         | string   | Yes      | Clean action description (verb + object + recipient)      |
| `direction`    | string   | Yes      | "outgoing", "incoming", or "third_party"                  |
| `deadline`     | string   | No       | Exact words from transcript, null if none mentioned       |
| `quote`        | string   | Yes      | Verbatim quote from transcript containing the commitment  |
| `uncertain`    | boolean  | No       | True if the commitment is weak/hedged                     |
| `conditional`  | boolean  | No       | True if depends on a condition                            |

---

## 6. Scoring Rubric

### 6.1 Commitment Detection (unit = one commitment)

| Outcome            | Definition                                                    | Score |
|--------------------|---------------------------------------------------------------|-------|
| **Exact Match**    | System found the same commitment as ground truth              | TP    |
| **Partial Match**  | System found the commitment but with wrong fields             | TP*   |
| **Miss**           | Ground truth has it, system did not find it                   | FN    |
| **False Positive** | System extracted something that is not a real commitment      | FP    |

**Matching criteria for "same commitment":**
Two commitments are considered a match if they refer to the same speech act.
Specifically, they share the same WHO and the same WHAT (core action).
Minor differences in wording of `text` are acceptable. The `quote` field
serves as the anchor -- if quotes overlap significantly, it is a match.

### 6.2 Field Accuracy (evaluated only on matched commitments)

| Field       | Scoring                                                          |
|-------------|------------------------------------------------------------------|
| `direction` | Exact match required: outgoing/incoming/third_party              |
| `who`       | Correct if same speaker identified (label or name)               |
| `to_whom`   | Correct if same recipient identified (label or name)             |
| `deadline`  | Correct if same deadline extracted (exact words); null=null match |

### 6.3 Aggregate Metrics

```
Precision = TP / (TP + FP)         -- "Of what system found, how much is real?"
Recall    = TP / (TP + FN)         -- "Of what exists, how much did system find?"
F1        = 2 * P * R / (P + R)    -- Harmonic mean

Field accuracy = correct_field / total_matched  (per field)
```

### 6.4 Quality Thresholds (from Murati)

| Metric    | Minimum acceptable | Target  |
|-----------|--------------------|---------|
| Precision | 0.70               | >= 0.85 |
| Recall    | 0.70               | >= 0.85 |
| F1        | 0.70               | >= 0.85 |
| Direction | 0.85               | >= 0.95 |
| Who       | 0.80               | >= 0.90 |
| Deadline  | 0.75               | >= 0.85 |

---

## 7. Annotation Instructions

For each call in the evaluation set:

1. Read the full transcript carefully.
2. Identify every statement that meets the commitment definition (Section 1).
3. For each commitment, fill in all fields (Section 5).
4. Check against the NOT-a-commitment list (Section 2).
5. Review edge cases (Section 3) for ambiguous items.
6. Use the scoring rubric (Section 6) to self-check consistency.

**Annotation tips:**
- When in doubt whether something is a commitment, include it with `uncertain: true`.
- Always copy the exact quote from the transcript for the `quote` field.
- For `text`, write a clean action command: "[Verb] [object] [to recipient]".
- If SPEAKER_ME is the committer, direction is "outgoing".
- If deadline is not mentioned, set `deadline` to `null`.
