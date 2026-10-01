# T41b: in-scope ABSTAIN triage (decisions/0018, criterion 5)

5 of the candidate's in-scope answers carry a trailing `DECISION: ABSTAIN`. Each is shown beside what control `_a` wrote for the same question, with both token counts. Classify each by hand as: control also refused / content lost / label disagrees with its own body.

## adversarial-01 (adversarial)

- candidate (34 tokens, t40_refusal=True):
  > The provided text does not contain information regarding athletic scholarships for the basketball team or the amount of money available for walk-on athletes.
- control `_a` (30 tokens, t40_refusal=True):
  > I cannot answer this question because the provided passages do not contain information regarding athletic scholarships for the basketball team or financial awards for walk-on athletes.

## cs-14 (cross_silo)

- candidate (122 tokens, t40_refusal=False):
  > The provided text does not mention a "Child Development with Teacher Licensure" major. While it mentions a "Child Development and Learning" degree in the context of an alumna (Source [5]), it does not specify if a licensure track exists for that major or where such a major would be housed.

Regarding the licensure process in general, the Division of Education coordinates the teacher licensure screening process, field experiences, instruction in Professional Education courses, and supervision of student teachers, although each major track is housed within its corresponding discipline of study (Source [1], [2]).
- control `_a` (67 tokens, t40_refusal=False):
  > The provided text does not mention a "Child Development with Teacher Licensure" major. While it mentions a "Child Development and Learning" degree in the context of an alumna [5], it does not specify if a licensure track exists for that major, where such a major would be housed, or the specific coursework requirements for it.

## cs-26 (cross_silo)

- candidate (96 tokens, t40_refusal=False):
  > The provided passages do not state whether a student will know their specific aid package amount by the time they attend the SOAR program. While the passages mention that "The Business of the College" session at SOAR provides "important information regarding billing and aid" [1] and that "distribution of estimated financial aid packages begins in December" [4], they do not specify the timing of aid package determination relative to the SOAR program dates.
- control `_a` (85 tokens, t40_refusal=False):
  > The provided passages do not state whether a student will know their specific aid package amount by the time they attend SOAR. While the passages mention that "The Business of the College" session at SOAR provides "important information regarding billing and aid" [1] and that estimated financial aid packages are distributed beginning in December [4], they do not specify the timing of aid package determination relative to the SOAR program dates.

## cs-28 (cross_silo)

- candidate (28 tokens, t40_refusal=True):
  > The provided passages do not contain information regarding Family Weekend or whether it is the same event as Homecoming.
- control `_a` (21 tokens, t40_refusal=True):
  > The provided passages do not contain information regarding Family Weekend or whether it is the same event as Homecoming.

## cs-63 (cross_silo)

- candidate (61 tokens, t40_refusal=False):
  > The provided text does not state whether the SMILE Scholarship is connected to the Bonner program or if it is applied for separately; it only mentions that the scholarship's honoree, Karson Leitch Beaty, was a Bonner Scholar while at Maryville College.
- control `_a` (77 tokens, t40_refusal=False):
  > The provided text does not state whether the SMILE Scholarship is connected to the Bonner program or if it is applied for separately; it only mentions that the scholarship's honoree, Karson Leitch Beaty, was a Bonner Scholar while at Maryville College.

Source: https://www.maryvillecollege.edu/giving/donor-recognition/donor-stories/
