# Phase 3b sanity-check review sheet

25 questions, naive generator over the Phase 3a retrieval baseline. Hand-score each answer 0/1/2 (0 = wrong/ungrounded, 1 = partial, 2 = correct and grounded in the cited passages) -- fill in the blank after `Score:` on each entry. No LLM judge at this n (PLAN Phase 3b).

## adversarial-10 (adversarial)

**Q:** Since my enrollment deposit is non-refundable the moment I pay it, is there any point in paying it early if I'm still deciding on another school?

**A:** According to Maryville College’s deposit policy, the $300 tuition deposit is **not waived** but it **is refundable** if you notify the college that you will not attend by the specified deadlines (May 1 for August admits or December 1 for January admits).  
Because the deposit can be refunded up to those dates, there is no advantage to paying it early if you are still weighing other schools—you can wait until you have made a decision and still receive a refund if you choose not to enroll.  

Source: “Pay the $300 tuition deposit… We will not waive this deposit… You may receive a refund if you inform us that you will not attend by May 1st (August admits) or December 1st (January admits).” (https://www.maryvillecollege.edu/international/admissions/undergraduate-degree/)

retrieval: recall@k=0.00 mrr=0.00 ndcg@k=0.00 all_golds_retrieved@k=0.00 | prompt 1666 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `1aa4a27a24f3a077-2` -- Undergraduate / Degree -- <https://www.maryvillecollege.edu/international/admissions/undergraduate-degree/>
- `dc806b79c9dc5876-3` -- Family FAQ -- <https://www.maryvillecollege.edu/families/new/faq/>
- `4f4087afd4a62e09-1` -- Required Proof of Funding for I-20 -- <https://www.maryvillecollege.edu/international/admissions/proof-of-funds/>
- `55c0dd03aa0fa10d-0` -- Student Statements and Payment Information -- <https://www.maryvillecollege.edu/business-office/billing/>
- `037720fd5ea00e94-2` -- Transfer -- <https://www.maryvillecollege.edu/international/admissions/transfer-students/>

Score: 2

## adversarial-12 (adversarial)

**Q:** Since MC is a test-optional school with no exceptions, I shouldn't need to submit an ACT or SAT score to get into the Education Preparation Program, right?

**A:** No. Even though Maryville College is test‑optional for most programs, the Education Preparation Program (EPP) has a separate requirement from the Tennessee Department of Education. Candidates must submit a qualifying score of **ACT 21 or higher** or **SAT 1080 or higher** to be considered for initial entry into the EPP【2】.

retrieval: recall@k=1.00 mrr=0.50 ndcg@k=0.63 all_golds_retrieved@k=1.00 | prompt 1758 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `42d979d46ce1a1ab-0` -- Enrollment Checklist -- <https://www.maryvillecollege.edu/admissions/resources/enrollment-checklist/>
- `067e0fc1c1d8ba11-0` -- Education Preparation Program -- <https://www.maryvillecollege.edu/academics/divisions/education/epp/>
- `291b1b51fd3f6db7-1` -- Applying for Admission -- <https://www.maryvillecollege.edu/admissions/apply/>
- `56d46f8993297c83-2` -- Future Student Resources -- <https://www.maryvillecollege.edu/admissions/resources/>
- `2ba1b5d1e2555c29-0` -- Conditional Admission -- <https://www.maryvillecollege.edu/international/admissions/conditional/>

Score: 2

## adversarial-01 (adversarial)

**Q:** Since Maryville College hands out athletic scholarships for its basketball team, how much money could I get if I walked on?

**A:** The passages you provided do not contain any information about athletic scholarships for Maryville College’s basketball team, so I can’t tell you how much money you might receive as a walk‑on.

retrieval: recall@k=0.00 mrr=0.00 ndcg@k=0.00 all_golds_retrieved@k=0.00 | prompt 1409 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `5b7e6d6ac9ba5c69-1` -- Mountain Challenge F.G.H. -- <https://www.maryvillecollege.edu/campus-life/mtn-challenge-fit-green-happy/>
- `7b6560937d6779a2-0` -- Scholarships & Awards for First-Year Students -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/scholarships-awards/first-year/>
- `52ff55203aa99575-0` -- Costs and Scholarships -- <https://www.maryvillecollege.edu/international/admissions/costs/>
- `0b4136a84db15bef-0` -- Scholarships & Awards for Transfer Students -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/scholarships-awards/transfer-students/>
- `72a00f7b7042a8b5-0` -- Tuition and Fees -- <https://www.maryvillecollege.edu/admissions/tuition-and-fees/>

Score: 2

## cs-14 (cross_silo)

**Q:** I want to major in Child Development with Teacher Licensure. Is that major housed in the Education division, and do I have to go through their separate licensure program on top of my major coursework?

**A:** I’m sorry, but the passages you provided do not contain any information about a **Child Development** major with teacher licensure. They describe the general structure of teacher‑licensure tracks and how the Division of Education coordinates the licensure process, but they do not list specific majors or confirm whether a Child Development major is housed in the Education division. If you need details about that particular major, you’ll need to consult Maryville College’s official program‑of‑study pages or contact the college directly.

retrieval: recall@k=0.50 mrr=1.00 ndcg@k=0.61 all_golds_retrieved@k=0.00 | prompt 1415 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `5a43f554bb1715f4-0` -- Division of Education -- <https://www.maryvillecollege.edu/academics/divisions/education/>
- `3db22dc23037b5d5-0` -- Education -- <https://www.maryvillecollege.edu/academics/programs-of-study/education/>
- `d71b5c7f85ad136e-0` -- Contemporary and Professional Issues in Psychology -- <https://www.maryvillecollege.edu/academics/course/psy299/>
- `62e28820294c2aee-0` -- Majors -- <https://www.maryvillecollege.edu/academics/resources/majors/>
- `421211640d8fa67e-1` -- Education -- <https://www.maryvillecollege.edu/academics/programs-of-study/education/>

Score: 1

## cs-25 (cross_silo)

**Q:** At SOAR they mentioned a 'Career Readiness' session run by the Career Center -- is that the same thing as the 'Scottie 9' I keep hearing about?

**A:** I’m sorry, but the passages you provided do not contain any information about a “Career Readiness” session that is offered during SOAR. The only reference to career‑related programming is the description of the **Scottie 9 Career Readiness Competencies** that the Career Center supports students in developing (see passage [1]). The Career Center’s services page lists general career‑coaching and professional‑development appointments (passage [5]), but it does not mention a specific SOAR session.

Because the available passages do not link the SOAR “Career Readiness” session to the Scottie 9 competencies, I can’t confirm that they are the same. If you need more detail, you might want to check the SOAR program materials or contact the Career Center directly.

retrieval: recall@k=0.50 mrr=1.00 ndcg@k=0.61 all_golds_retrieved@k=0.00 | prompt 1824 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `9fee75fb8ad465b3-0` -- Scottie Career Competencies -- <https://www.maryvillecollege.edu/academics/career-center/scottie-9/>
- `5a89c28bbf8dd45c-2` -- SOAR -- <https://www.maryvillecollege.edu/orientation/soar/>
- `bf226c426e6e6f70-0` -- SOAR -- <https://www.maryvillecollege.edu/orientation/soar/>
- `cafe5ef062557e69-4` -- New Scots Orientation – Fall 26 -- <https://www.maryvillecollege.edu/orientation/new-scots/>
- `e125bcf15a4a2302-0` -- Career Center Services -- <https://www.maryvillecollege.edu/academics/career-center/career-services/>

Score: 2

## cs-44 (cross_silo)

**Q:** After I get back from studying abroad, the return-resources page told me to check the Career Center for overseas job leads. Does the Career Center actually keep a list of jobs abroad, or is that just generic career coaching?

**A:** The return‑resources page specifically says that the Career Center “researches overseas employment opportunities.” This indicates that the Career Center offers resources for jobs abroad, not just generic career coaching.  
Source: [5] “Career Center: research overseas employment opportunities at Career Center. You just might be able to find a job that will get you back.”

retrieval: recall@k=0.50 mrr=0.20 ndcg@k=0.24 all_golds_retrieved@k=0.00 | prompt 1475 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `d5aabb4bffbecd9a-2` -- MC Scots Abroad Return -- <https://www.maryvillecollege.edu/international/studyabroad/mcscotsabroadreturn/>
- `6c76fae951999d57-3` -- MC Scots Abroad Return -- <https://www.maryvillecollege.edu/international/studyabroad/mcscotsabroadreturn/>
- `4794ba49d00c8dfa-1` -- Study/Intern Abroad -- <https://www.maryvillecollege.edu/international/studyabroad/>
- `3c5ec5a1f6a64d17-4` -- Pre-Departure Information -- <https://www.maryvillecollege.edu/international/studyabroad/predeparture/>
- `6e3165ad6e8e7a5d-4` -- MC Scots Abroad Return -- <https://www.maryvillecollege.edu/international/studyabroad/mcscotsabroadreturn/>

Score: 1

## cs-63 (cross_silo)

**Q:** The SMILE Scholarship donor story mentions the honoree was a Bonner Scholar -- is the SMILE Scholarship connected to the Bonner program, or would I apply for it completely separately?

**A:** The SMILE Scholarship is a separate award.  
The donor‑story passage notes that the honoree, Karson Leitch Beaty, was a Bonner Scholar, but it does not say that the SMILE Scholarship is part of the Bonner program. Therefore you would apply for the SMILE Scholarship on its own, independently of the Bonner Scholars Program.  

Source: Donor Stories passage, “SMILE Scholarship reflects a life committed to service, leadership, and ‘doing good on the largest possible scale.’ … Karson Leitch Beaty … was a Bonner Scholar at Maryville College.” (https://www.maryvillecollege.edu/giving/donor-recognition/donor-stories/)

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=0.88 all_golds_retrieved@k=1.00 | prompt 1685 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `919d92d9bfa38f86-0` -- Bonner Scholars Program -- <https://www.maryvillecollege.edu/campus-life/community-engagement-center/bonner-scholars-program/>
- `6c51e901d7b2d7f1-0` -- MC VOTES -- <https://www.maryvillecollege.edu/campus-life/community-engagement-center/mc-votes/>
- `e5a0597b7ae0d0fe-4` -- Scholarships & Awards for First-Year Students -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/scholarships-awards/first-year/>
- `c711c98caafc9575-13` -- Donor Stories -- <https://www.maryvillecollege.edu/giving/donor-recognition/donor-stories/>
- `d904345f8bb02701-2` -- Scholarships & Awards for First-Year Students -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/scholarships-awards/first-year/>

Score: 1

## cs-17 (cross_silo)

**Q:** The Quick Facts page says MC is committed to an environment free from discrimination and mentions Title IX -- if I actually need to report something, who do I contact?

**A:** If you need to report a violation, you should contact the **Title IX Coordinator**.  
The college’s policy states: “For additional information on nondiscrimination policies and concerns about violations, contact the Title IX Coordinator at **titleix@maryvillecollege.edu**”【2】.

retrieval: recall@k=0.00 mrr=0.00 ndcg@k=0.00 all_golds_retrieved@k=0.00 | prompt 1657 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `86f49d13ca89a655-4` -- XII. Discrimination, Harassment and Title IX Policies – DRAFT -- <https://www.maryvillecollege.edu/campus-life/student-services/handbook/discrimination-harassment-titleix/harassment-title-ix-draft/>
- `5880b2c0413132b6-0` -- XI. Statement of Non-discrimination -- <https://www.maryvillecollege.edu/campus-life/student-services/handbook/non-discrimination/>
- `8765edb84f31ee31-0` -- Community & Belonging -- <https://www.maryvillecollege.edu/about/mission-vision/community-belonging/>
- `b70f8d74a1e4aadc-3` -- XIII. Code of Conduct -- <https://www.maryvillecollege.edu/campus-life/student-services/handbook/conduct/>
- `2d17e9d7a76cf8b0-2` -- XII. Discrimination, Harassment and Title IX Policies – DRAFT -- <https://www.maryvillecollege.edu/campus-life/student-services/handbook/discrimination-harassment-titleix/harassment-title-ix-draft/>

Score: 2

## cs-26 (cross_silo)

**Q:** SOAR includes a 'Business of the College' session about billing and financial aid -- will I actually know my aid package amount by the time I go to SOAR, or is that decided later?

**A:** The passages you provided do not contain information about when a student’s aid package amount is finalized relative to the SOAR program. They describe the SOAR sessions and the general billing timeline, but they do not state whether the aid package is known by the time of SOAR or decided afterward.

retrieval: recall@k=0.00 mrr=0.00 ndcg@k=0.00 all_golds_retrieved@k=0.00 | prompt 1703 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `9fdae214de11bf53-0` -- Important Dates -- <https://www.maryvillecollege.edu/business-office/dates/>
- `bf226c426e6e6f70-0` -- SOAR -- <https://www.maryvillecollege.edu/orientation/soar/>
- `55c0dd03aa0fa10d-0` -- Student Statements and Payment Information -- <https://www.maryvillecollege.edu/business-office/billing/>
- `dc806b79c9dc5876-3` -- Family FAQ -- <https://www.maryvillecollege.edu/families/new/faq/>
- `754d70dbedb4c918-1` -- Charge Reduction Policy -- <https://www.maryvillecollege.edu/admissions/finaid/resources/charge-reduction/>

Score: 0

## cs-70 (cross_silo)

**Q:** The Great Smokies Experience program is co-run with the Great Smoky Mountains Institute at Tremont and Mountain Challenge -- if I do that program in high school, does the Career Center get involved at all, or is it purely an academic/outdoor program?

**A:** The Great Smokies Experience is described only as a credit‑bearing, hands‑on environmental education program coordinated by Mary Ville College faculty, the Great Smoky Mountains Institute at Tremont, and Mountain Challenge. None of the passages mention the Career Center or any career‑services component. Therefore, if you participate in the program while still in high school, the Career Center is not involved; it is purely an academic/outdoor experience.  

Sources:  
- GSE Application page (high‑school eligibility, academic credit) – https://www.maryvillecollege.edu/about/community-education/gse/application/  
- Great Smokies Experience page (program description, credit) – https://www.maryvillecollege.edu/about/community-education/gse/  
- FAQ page (program details, no Career Center mention) – https://www.maryvillecollege.edu/about/community-education/gse/faq/

retrieval: recall@k=0.50 mrr=0.33 ndcg@k=0.31 all_golds_retrieved@k=0.00 | prompt 1512 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `2bae39cc17e3ca1e-0` -- GSE Application -- <https://www.maryvillecollege.edu/about/community-education/gse/application/>
- `bb1bab1c5fdce109-1` -- Experiential Learning -- <https://www.maryvillecollege.edu/academics/learn-by-experience/>
- `53d72a4fbc37aca4-0` -- Great Smokies Experience -- <https://www.maryvillecollege.edu/about/community-education/gse/>
- `b8c25a60c759c49a-2` -- Our FAQ -- <https://www.maryvillecollege.edu/about/community-education/gse/faq/>
- `c8f104676b0c5b74-1` -- Our FAQ -- <https://www.maryvillecollege.edu/about/community-education/gse/faq/>

Score: 2

## exact-04 (exact_match)

**Q:** What's the prerequisite for ENG191, American Literature: Puritan through Romantic?

**A:** The prerequisite for ENG191, American Literature: Puritan through Romantic, is **ENG 120 or equivalent placement**.  
Source: https://www.maryvillecollege.edu/academics/course/american-literature-puritan-through-romantic/

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 733 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `c23b27f8630b7828-0` -- American Literature: Puritan through Romantic -- <https://www.maryvillecollege.edu/academics/course/american-literature-puritan-through-romantic/>
- `3b3bc186ebe9e2ac-0` -- American Literature: Puritan Through Romantic -- <https://www.maryvillecollege.edu/academics/course/eng221/>
- `4657dabee7940688-0` -- The Modern Western Literary Tradition -- <https://www.maryvillecollege.edu/academics/course/eng170/>
- `60d2210103a2d851-0` -- Literature and the American Experience -- <https://www.maryvillecollege.edu/academics/course/eng180/>
- `84a21a30410ed4e3-0` -- American Literature: Realism to the Present -- <https://www.maryvillecollege.edu/academics/course/american-literature-realism-to-the-present/>

Score: 2

## exact-16 (exact_match)

**Q:** What's the white card in my passport called that gets issued at the U.S. port of entry?

**A:** The white card in your passport that is issued at the U.S. port of entry is called the **I‑94**. It is the arrival‑departure record that shows your status in the United States. (Source: https://www.maryvillecollege.edu/international/iss/immigration/)

retrieval: recall@k=1.00 mrr=0.50 ndcg@k=0.63 all_golds_retrieved@k=1.00 | prompt 1696 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `4db82e23ded9748c-1` -- Student Employment Forms of ID -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/student-employment-overview/forms-of-id/>
- `06b9bbba2a399583-0` -- Immigration Information -- <https://www.maryvillecollege.edu/international/iss/immigration/>
- `8512415badf934a0-1` -- Pre-Departure Information -- <https://www.maryvillecollege.edu/international/studyabroad/predeparture/>
- `717a4dce67c33a9b-0` -- Student Employment Forms of ID -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/student-employment-overview/forms-of-id/>
- `fd45a6cd556a09be-1` -- Immigration Information -- <https://www.maryvillecollege.edu/international/iss/immigration/>

Score: 2

## exact-07 (exact_match)

**Q:** What's the course code for Senior Study I in the Education program?

**A:** The course code for Senior Study I in the Education program is **EDU351**【1】.

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 674 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `1aaa2c57d1fbf1eb-0` -- Senior Study I -- <https://www.maryvillecollege.edu/academics/course/senior-study-i/>
- `e83bcc5f71a6536c-0` -- Senior Study -- <https://www.maryvillecollege.edu/academics/course/edu351-352-2/>
- `6172bde9a84158b8-0` -- Selected Topics in Education -- <https://www.maryvillecollege.edu/academics/course/edu149-249-349/>
- `ad3b11003c1c2636-0` -- Senior Study -- <https://www.maryvillecollege.edu/academics/course/exs351-352/>
- `189482f91999aa11-0` -- Senior Project -- <https://www.maryvillecollege.edu/academics/course/dsn351-352-2/>

Score: 2

## mt-07 (multi_turn)

**Q:** Does she need a certain GPA or test score to qualify?

**A:** **Answer**

| Program / Scholarship | GPA requirement | Test‑score requirement | Source |
|-----------------------|-----------------|------------------------|---------|
| **Education Preparation Program (EPP)** | Minimum overall GPA of **2.75** (or 2.5+ to request a GPA waiver) | • ACT score **≥ 21**  <br>• SAT score **≥ 1080** | [2](https://www.maryvillecollege.edu/academics/divisions/education/epp/), [4](https://www.maryvillecollege.edu/academics/divisions/education/epp/) |
| **Conditional Admission (International students)** | Not applicable | English‑proficiency test score (e.g., TOEFL, IELTS, etc.) must meet the college’s minimum requirement | [3](https://www.maryvillecollege.edu/international/admissions/conditional/) |
| **Non‑Traditional HOPE Scholarship** | No GPA requirement listed | No test‑score requirement listed (only the standard HOPE scholarship criteria) | [1](https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/tennessee-state-aid/different-types-of-state-scholarships/) |

**Summary**

- If she is applying to the **Education Preparation Program**, she must have at least a 2.75 overall GPA and either an ACT score of 21 or higher, or an SAT score of 1080 or higher.  
- If she is applying for **conditional admission** as an international student, she must provide an acceptable English‑proficiency test score.  
- For the **Non‑Traditional HOPE Scholarship**, the passages do not list any GPA or test‑score requirement beyond the standard HOPE criteria.

retrieval: recall@k=0.00 mrr=0.00 ndcg@k=0.00 all_golds_retrieved@k=0.00 | prompt 1547 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `a55e4881d812519c-1` -- Different Types of State Scholarships -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/tennessee-state-aid/different-types-of-state-scholarships/>
- `9950ab7addb06c62-1` -- Education Preparation Program -- <https://www.maryvillecollege.edu/academics/divisions/education/epp/>
- `2ba1b5d1e2555c29-0` -- Conditional Admission -- <https://www.maryvillecollege.edu/international/admissions/conditional/>
- `067e0fc1c1d8ba11-0` -- Education Preparation Program -- <https://www.maryvillecollege.edu/academics/divisions/education/epp/>
- `c95f5fd43574ab5b-0` -- Waiver Request -- <https://www.maryvillecollege.edu/academics/divisions/education/waiver-request/>

Score: 2

## ss-74 (single_silo)

**Q:** Can I donate to MC straight from my IRA to cover my required minimum distribution?

**A:** The passages indicate that you can make a gift directly from your IRA to Maryville College, but they do not address whether such a gift can be used to satisfy a required minimum distribution (RMD). Therefore, the information you’re looking for isn’t provided in the supplied passages.  

Source: [1] https://www.maryvillecollege.edu/giving/ways-to-give/

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 1666 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `f50de305c3452e3a-2` -- All the Ways to Give -- <https://www.maryvillecollege.edu/giving/ways-to-give/>
- `599c000d80f16408-1` -- All the Ways to Give -- <https://www.maryvillecollege.edu/giving/ways-to-give/>
- `0b79c7c018f47691-0` -- Giving Securities / Stock -- <https://www.maryvillecollege.edu/giving/ways-to-give/stock-securities/>
- `094ab913c067c6c6-1` -- Fundraising on Campus -- <https://www.maryvillecollege.edu/business-office/fundraising/>
- `4ae6ad5bb4600db5-2` -- Fundraising on Campus -- <https://www.maryvillecollege.edu/business-office/fundraising/>

Score: 2

## pilot-ss-06 (single_silo)

**Q:** How much does a standard double room cost per semester, and which halls have standard rooms?

**A:** The standard double room costs **$3,440 per semester**【1】.  
Standard rooms are available in the following residence halls: **Copeland, Davis, Gamble, and most of Pearsons Hall**【1】.

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 2016 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `c145c2ff67d6edbc-0` -- Room & Meal Plan Prices -- <https://www.maryvillecollege.edu/campus-life/reslife/residence-halls/prices/>
- `f2ab17545f66c34c-1` -- Residence Halls -- <https://www.maryvillecollege.edu/campus-life/reslife/residence-halls/>
- `c47f5a5de505dfd8-3` -- Residence Halls -- <https://www.maryvillecollege.edu/campus-life/reslife/residence-halls/>
- `7e901a58111aed36-1` -- Tuition and Fees -- <https://www.maryvillecollege.edu/admissions/tuition-and-fees/>
- `cc98039e15160259-10` -- XV. Residence Hall Policies & Procedures -- <https://www.maryvillecollege.edu/campus-life/student-services/handbook/residence-hall-policies/>

Score: 2

## ss-17 (single_silo)

**Q:** What are the cash prizes for the Hall Ethical Thinking Award this year, and when's it due?

**A:** The Hall Ethical Thinking Award offers the following cash prizes for this year:

- **First prize:** $4,500  
- **Second prize:** $3,100  
- **Third prize:** $2,400  

The submission deadline is **12:00 noon on Monday, February 9, 2026**.  

Source: https://www.maryvillecollege.edu/academics/divisions/social-sciences/ethical-thinking/ (passage [1])

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 1800 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `490b75ba811582b7-0` -- The Hall Ethical Thinking Award Contest -- <https://www.maryvillecollege.edu/academics/divisions/social-sciences/ethical-thinking/>
- `0ecfd1bd386d4646-1` -- The Hall Ethical Thinking Award Contest -- <https://www.maryvillecollege.edu/academics/divisions/social-sciences/ethical-thinking/>
- `71591dda3df38017-2` -- Cummings Conversations at Maryville College -- <https://www.maryvillecollege.edu/about/faith/cummings-conversations/>
- `76463db3c122a05a-1` -- Global Travel Study & Athletic Programs -- <https://www.maryvillecollege.edu/international/studyabroad/programs/travelstudy/>
- `3c5526dc10b55e47-3` -- Scholarships & Awards for First-Year Students -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/scholarships-awards/first-year/>

Score: 2

## ss-69 (single_silo)

**Q:** How much does the Great Smokies Experience summer program actually cost, and what does that cover?

**A:** The Great Smokies Experience summer program costs **$1,999**.  
That fee covers:

* All tuition and program fees  
* Room and board for the duration of the trip  
* Transportation to and from the Great Smoky Mountains National Park  
* Transportation to and from all scheduled field trips  

Tennessee residents may be eligible for a dual‑enrollment grant of up to **$600** off this cost.  
Source: https://www.maryvillecollege.edu/about/community-education/gse/faq/

retrieval: recall@k=1.00 mrr=0.50 ndcg@k=0.63 all_golds_retrieved@k=1.00 | prompt 1373 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `4b6beb32cb3a8ba7-0` -- GSE Registration -- <https://www.maryvillecollege.edu/about/community-education/gse/registration/>
- `8756728d3fa8f883-0` -- Our FAQ -- <https://www.maryvillecollege.edu/about/community-education/gse/faq/>
- `53d72a4fbc37aca4-0` -- Great Smokies Experience -- <https://www.maryvillecollege.edu/about/community-education/gse/>
- `2bae39cc17e3ca1e-0` -- GSE Application -- <https://www.maryvillecollege.edu/about/community-education/gse/application/>
- `b8c25a60c759c49a-2` -- Our FAQ -- <https://www.maryvillecollege.edu/about/community-education/gse/faq/>

Score: 2

## ss-76 (single_silo)

**Q:** Does Maryville College hold a graduation ceremony in December, or only in the spring?

**A:** Mary College’s graduation ceremony (the Commencement exercises) is held annually at the close of the spring semester in May.  While students who finish their requirements by December may still participate in the spring ceremony by submitting a Degree Completion Plan, the college does not hold a separate December graduation ceremony.  

Source: “Degrees are formally conferred at the Commencement exercises held annually at the close of the Spring Semester in May…Students who do not complete all requirements by the close of the Spring Semester may participate in Commencement exercises only if they can submit a Degree Completion Plan indicating completion of all requirements by December of that same year.” (https://www.maryvillecollege.edu/academics/registrar/degrees/)

retrieval: recall@k=1.00 mrr=0.25 ndcg@k=0.43 all_golds_retrieved@k=1.00 | prompt 1523 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `e6858b90f90942dc-0` -- 2026 Commencement / Graduation Weekend -- <https://www.maryvillecollege.edu/families/visiting-the-college/commencement/>
- `8de54d91efc1ccd2-0` -- Degrees Awarded -- <https://www.maryvillecollege.edu/academics/registrar/degrees/>
- `bde7d1cd4a0c0ecd-1` -- Admissions -- <https://www.maryvillecollege.edu/admissions/>
- `d5e2b3a6bf7e2628-0` -- Glossary of College Lingo -- <https://www.maryvillecollege.edu/families/new/glossary/>
- `9d384af69535e854-1` -- Class of 1976 -- <https://www.maryvillecollege.edu/alumni/events/homecoming/class-of-1976/>

Score: 2

## ss-39 (single_silo)

**Q:** If I move apartments as an international student, how many days do I have to report it before I'm out of status?

**A:** 

retrieval: recall@k=1.00 mrr=0.50 ndcg@k=0.63 all_golds_retrieved@k=1.00 | prompt 1687 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `cc98039e15160259-10` -- XV. Residence Hall Policies & Procedures -- <https://www.maryvillecollege.edu/campus-life/student-services/handbook/residence-hall-policies/>
- `fd45a6cd556a09be-1` -- Immigration Information -- <https://www.maryvillecollege.edu/international/iss/immigration/>
- `06b9bbba2a399583-0` -- Immigration Information -- <https://www.maryvillecollege.edu/international/iss/immigration/>
- `92025f4429d403d6-0` -- Pre-Arrival Information -- <https://www.maryvillecollege.edu/international/iss/prearrival/>
- `30ec3758c079c363-0` -- Pre-Departure Information -- <https://www.maryvillecollege.edu/international/studyabroad/predeparture/>

Score: 0

## ss-72 (single_silo)

**Q:** How much do I need to donate in a year to join MC's President's Circle giving society?

**A:** To become a member of Maryville College’s President’s Circle giving society, you must donate **$1,000 or more in a fiscal year** (June 1 – May 31).  

Source: [1] Giving Societies – https://www.maryvillecollege.edu/giving/donor-recognition/giving-societies/

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 1672 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `9997155539fb0b15-0` -- Giving Societies -- <https://www.maryvillecollege.edu/giving/donor-recognition/giving-societies/>
- `d049305b33a4fd52-1` -- Global Scholar Award & Fellowships -- <https://www.maryvillecollege.edu/international/admissions/global-scholar-award/>
- `3364cb81d95811c8-2` -- Costs and Scholarships -- <https://www.maryvillecollege.edu/international/admissions/costs/>
- `e2d016ce285e90e0-1` -- Church-Related Scholarships -- <https://www.maryvillecollege.edu/about/faith/related-scholarships/>
- `bd2e3589a2e35d02-8` -- Costs and Scholarships -- <https://www.maryvillecollege.edu/international/admissions/costs/>

Score: 2

## ss-16 (single_silo)

**Q:** Do I have to be a music major to play in the community band on campus?

**A:** No. The Maryville College‑Community Concert Band (MC3Band) is open to students of any major.  The program states that “regardless of your major or instrument, we can find a place for you” and that both music and non‑music majors are eligible to participate (and may even receive scholarships).  This is also reflected in the broader scholarship policy, which allows both majors and non‑majors to audition and join ensembles.  

Sources:  
- [2] “Regardless of your major or instrument, we can find a place for you!”  
- [3] “Both majors and non‑majors are eligible, provided they maintain active participation and contribute musically to campus life.”

retrieval: recall@k=1.00 mrr=0.50 ndcg@k=0.63 all_golds_retrieved@k=1.00 | prompt 1345 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `34e13c63c057c161-2` -- Instrumental Programs -- <https://www.maryvillecollege.edu/academics/divisions/fine-arts/instrumental-programs/>
- `fc9702ccdb8bb326-0` -- Instrumental Programs -- <https://www.maryvillecollege.edu/academics/divisions/fine-arts/instrumental-programs/>
- `23cfcbee5ef24522-2` -- Scholarships and Auditions -- <https://www.maryvillecollege.edu/academics/divisions/fine-arts/scholarships-and-auditions/>
- `397e0697e09df24a-0` -- Ensemble Music -- <https://www.maryvillecollege.edu/academics/course/musens/>
- `a3ecb807411537ef-10` -- Costs and Scholarships -- <https://www.maryvillecollege.edu/international/admissions/costs/>

Score: 2

## temporal-11 (temporal)

**Q:** If I need to request a GPA or Testing Waiver for the Education program, what's the actual submission deadline tied to?

**A:** The waiver must be submitted **before the end of the semester that precedes the semester in which you take EDU 351 Senior Study I**.  
This applies to both the GPA waiver and the testing waiver for the Education program.  

Source: [1] Waiver Request – Maryville College Education Division.

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 1337 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `c95f5fd43574ab5b-0` -- Waiver Request -- <https://www.maryvillecollege.edu/academics/divisions/education/waiver-request/>
- `dc806b79c9dc5876-3` -- Family FAQ -- <https://www.maryvillecollege.edu/families/new/faq/>
- `618adca274c6563c-1` -- Application Process -- <https://www.maryvillecollege.edu/admissions/finaid/application/>
- `2819ee69789e8fa4-2` -- MC Scots in Amsterdam 2022 -- <https://www.maryvillecollege.edu/international/studyabroad/programs/travelstudy/mcinamsterdam2022/>
- `8f05b72569e4fb14-0` -- Application Deadlines -- <https://www.maryvillecollege.edu/admissions/apply/application-deadlines/>

Score: 2

## temporal-13 (temporal)

**Q:** When's the deadline to apply for the $600 Tennessee dual-enrollment grant that helps cover GSE tuition?

**A:** The deadline for the Tennessee dual‑enrollment grant that can cover up to $600 of the GSE tuition is **typically in mid‑May** for summer classes.  
Source: https://www.maryvillecollege.edu/about/community-education/gse/faq/

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 1606 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `8756728d3fa8f883-0` -- Our FAQ -- <https://www.maryvillecollege.edu/about/community-education/gse/faq/>
- `aca50253f5da167e-0` -- HOPE Eligibility -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/tennessee-state-aid/hope-eligibility/>
- `8b779b3332c775dc-4` -- Applying for Admission -- <https://www.maryvillecollege.edu/admissions/apply/>
- `95533786fe722680-0` -- Tennessee State Aid -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/tennessee-state-aid/>
- `e1c7e64cd2571220-0` -- Financial Aid Services -- <https://www.maryvillecollege.edu/business-office/finaid/>

Score: 2

## temporal-10 (temporal)

**Q:** By when in my time at MC do I need to have applied for Initial Entry into the Education Preparation Program?

**A:** You must apply for Initial Entry into the Education Preparation Program no later than the **second semester of your Sophomore year** at Maryville College.  

Source: Education Preparation Program – https://www.maryvillecollege.edu/academics/divisions/education/epp/

retrieval: recall@k=1.00 mrr=1.00 ndcg@k=1.00 all_golds_retrieved@k=1.00 | prompt 1649 tok / budget 7104 tok (truncation risk: False)

Retrieved:
- `067e0fc1c1d8ba11-0` -- Education Preparation Program -- <https://www.maryvillecollege.edu/academics/divisions/education/epp/>
- `42d979d46ce1a1ab-0` -- Enrollment Checklist -- <https://www.maryvillecollege.edu/admissions/resources/enrollment-checklist/>
- `319c31250d6de9fe-0` -- Apply to Study/Intern Abroad -- <https://www.maryvillecollege.edu/international/studyabroad/applications/>
- `e28d496437ad964a-1` -- Apply to Study/Intern Abroad -- <https://www.maryvillecollege.edu/international/studyabroad/applications/>
- `a519f0cd27d66f8f-3` -- Immigration Information -- <https://www.maryvillecollege.edu/international/iss/immigration/>

Score: 2
