# Gold set spot-check sample

20 questions, stratified across all 7 slices (random seed 7) -- for the Checkpoint C human review: does the cited gold ref actually contain the answer?

## ss-42 (single_silo)
**Q:** If I'm starting as an international student in the spring, when does the mandatory orientation actually happen?

- `4e11489478e58404-1` -- silo `['iss']` -- *International Student Orientation* -- <https://www.maryvillecollege.edu/international/iss/orientation/>

conjunctive: False | expected_referral: international@maryvillecollege.edu
notes: International Student Orientation chunk: spring-admit orientation takes place the 2 days immediately prior to the start of spring classes (vs. mid-August for fall).

## ss-20 (single_silo)
**Q:** My parents want their own copy of my grades mailed to them every semester -- what do I actually have to fill out for that?

- `cec42b5e04d3f581-0` -- silo `['academics']` -- *Grades* -- <https://www.maryvillecollege.edu/academics/registrar/grades/>

conjunctive: False | expected_referral: registrar@maryvillecollege.edu
notes: Registrar's Grades chunk: students complete an Authorization to Mail Grades Form per term (a separate form each term); email requests aren't accepted.

## ss-51 (single_silo)
**Q:** How many volunteers showed up for KT Days in 2026, and how many hours did they put in?

- `027e8298290ecb13-0` -- silo `['alumni']` -- *KT Days 2026 Wrap-Up* -- <https://www.maryvillecollege.edu/alumni/events/kin-takahashi/kt-days-2026-wrap/>

conjunctive: False | expected_referral: alumni@maryvillecollege.edu
notes: KT Days 2026 Wrap-Up chunk: 95 KT volunteers logged more than 1,900 hours across the three main days (plus KT 101/Alumni Brew Day), marking the 28th year of the tradition.

## pilot-ss-07 (single_silo)
**Q:** What ACT score or GPA do I need coming out of high school to qualify for the Tennessee HOPE scholarship at Maryville?

- `bc0ba6d65d62fa28-0` -- silo `['finaid']` -- *HOPE Eligibility* -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/tennessee-state-aid/hope-eligibility/>

conjunctive: False | expected_referral: financialaid@maryvillecollege.edu
notes: Finaid chunk states entering freshmen need a 21 ACT (1070 SAT) OR a 3.0 weighted GPA, plus TN residency and an eligible high school; a factual threshold question.

## cs-18 (cross_silo)
**Q:** I want to apply for both the Bonner Scholars Program and the Presbyterian Church & College Fellowship. Can I realistically do both, given the weekly volunteer hours each one requires?

- `2c540b5061c90044-2` -- silo `['faith_life']` -- *Church-Related Scholarships* -- <https://www.maryvillecollege.edu/about/faith/related-scholarships/>
- `77510f75e9dc73ae-0` -- silo `['community_engagement']` -- *Bonner Scholars Program* -- <https://www.maryvillecollege.edu/campus-life/community-engagement-center/bonner-scholars-program/>

conjunctive: True | expected_referral: community.engagement@maryvillecollege.edu
notes: The faith_life Church & College Fellowship chunk sets its commitment at three hours per week of local church service; the community_engagement Bonner Scholars chunk sets its commitment at 10 hours per week during the year plus summer hours. Only reading both lets a student add up the total time commitment before deciding.

## pilot-cs-07 (cross_silo)
**Q:** I'm on the HOPE scholarship. If I spend spring semester on an ISEP exchange, am I going to lose it?

- `87eb26c962060f36-0` -- silo `['finaid']` -- *Maintaining Hope Scholarship* -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/tennessee-state-aid/maintaining-hope-scholarship/>
- `ac24ada447254d72-1` -- silo `['study_abroad']` -- *Going Abroad FAQ* -- <https://www.maryvillecollege.edu/international/studyabroad/faq/>

conjunctive: True | expected_referral: financialaid@maryvillecollege.edu
notes: finaid Maintaining HOPE chunk: forfeiture if you drop below full-time or skip a fall/spring term; study_abroad FAQ chunk: on an MC bilateral/ISEP exchange you pay MC tuition, remain an enrolled MC student and stay eligible for aid. The reassurance only follows from reading both.

## cs-21 (cross_silo)
**Q:** I qualify for the Scots Legacy Award, which requires living on campus -- what would a standard double room actually cost me per semester?

- `b1ac5f2c5815ed77-0` -- silo `['finaid']` -- *Scots Legacy Award* -- <https://www.maryvillecollege.edu/admissions/finaid/scots-legacy-award/>
- `4814462949910569-0` -- silo `['residential']` -- *Room & Meal Plan Prices* -- <https://www.maryvillecollege.edu/campus-life/reslife/residence-halls/prices/>

conjunctive: True | expected_referral: financialaid@maryvillecollege.edu
notes: The finaid Scots Legacy Award chunk states the on-campus living requirement and the scholarship value but gives no room rate; the residential prices chunk gives the actual 2026-27 standard-room rate. A student can't judge the award's net value from either chunk alone.

## cs-55 (cross_silo)
**Q:** I don't yet have my English proficiency test scores back, but I still want to lock in my spot before the regular admissions deadline passes. Can I still apply on time as an international student?

- `35e2babfdc2fe071-0` -- silo `['admissions']` -- *Application Deadlines* -- <https://www.maryvillecollege.edu/admissions/apply/application-deadlines/>
- `2e61b1f88aca794b-0` -- silo `['iss']` -- *Conditional Admission* -- <https://www.maryvillecollege.edu/international/admissions/conditional/>

conjunctive: True | expected_referral: international@maryvillecollege.edu
notes: The admissions Application Deadlines chunk gives the Early Action and Regular Decision submission dates that apply broadly, without addressing missing test scores; the iss Conditional Admission chunk explains that students without English Proficiency scores can still apply and be conditionally admitted while they finish testing or language training. An international applicant needs both to know they won't miss the deadline just because scores are pending.

## oos-46 (out_of_scope)
**Q:** If I took BIO 1110 at Pellissippi State, will it transfer in as equivalent to Biology 113 here?

- (no gold refs -- out_of_scope)

conjunctive: False | expected_referral: registrar@maryvillecollege.edu
notes: Pellissippi State is mentioned repeatedly in the corpus, but only as faculty/alumni background (attended, taught, or worked there) or as a fair attendee; grepped 'articulation agreement' and 'transfer equivalen' across the whole corpus and found zero hits, so no course-to-course equivalency table exists.

## oos-12 (out_of_scope)
**Q:** How many credit hours is the Computer Science major and do I have to take a specific math sequence?

- (no gold refs -- out_of_scope)

conjunctive: False | expected_referral: registrar@maryvillecollege.edu
notes: The Computer Science program page describes clubs (MC3D, Computer Programming Team) and student stories but gives no credit-hour total or required math sequence; grep for 'Computer Science' near 'semester hours' turns up nothing itemized.

## pilot-oos-07 (out_of_scope)
**Q:** What's Maryville College's acceptance rate?

- (no gold refs -- out_of_scope)

conjunctive: False | expected_referral: admissions@maryvillecollege.edu
notes: Grep for 'acceptance rate', 'admit rate' and 'admission rate' returns zero chunks; Quick Facts gives enrollment and student-faculty ratio but not selectivity. Admissions plausibly owns the question.

## temporal-17 (temporal)
**Q:** As a new international student starting this fall, what date range does my mandatory MC health insurance actually cover?

- `6f9c127e6fa7768f-2` -- silo `['iss']` -- *International Student Health* -- <https://www.maryvillecollege.edu/international/iss/internationalhealth/>

conjunctive: False | expected_referral: international@maryvillecollege.edu
notes: The International Student Health page lists 'Fall: August 11. 2025 – January 9, 2026 $400 (new student rate)' under 'Cost & Coverage Dates (2025)' -- these coverage dates are for a past enrollment cycle, a strong test of whether the pipeline flags or surfaces an outdated policy period instead of presenting it as current.

## temporal-07 (temporal)
**Q:** What are the two SOAR overnight session dates I can pick from this summer?

- `dde75fa357130266-0` -- silo `['orientation']` -- *SOAR* -- <https://www.maryvillecollege.edu/orientation/soar/>

conjunctive: False | expected_referral: orientation@maryvillecollege.edu
notes: The SOAR page states 'SOAR 2026 Dates: June 26-27 or July 10-11' -- an explicitly year-stamped pair of dates that will need updating next cycle.

## temporal-02 (temporal)
**Q:** What's MC's priority deadline for filing my FAFSA online so it counts for Maryville College's own financial aid?

- `7ae9ea8c205ecde1-1` -- silo `['finaid']` -- *Application Process* -- <https://www.maryvillecollege.edu/admissions/finaid/application/>

conjunctive: False | expected_referral: financialaid@maryvillecollege.edu
notes: The Financial Aid Calendar in the Application Process chunk lists February 1 as the priority deadline for filing FAFSA online for Maryville College specifically (distinct from the TN state aid priority date on the same line).

## exact-03 (exact_match)
**Q:** What does the course code AEI149-249-349 cover?

- `5c73034fb05c40cb-0` -- silo `['academics']` -- *Selected Topics in American Sign Language-English Interpreting* -- <https://www.maryvillecollege.edu/academics/course/aei149-249-349/>

conjunctive: False | expected_referral: registrar@maryvillecollege.edu
notes: AEI149-249-349 is PLAN's own worked example of a course_code literal-leg pattern; the chunk's Code field is exactly 'AEI149-249-349' and Title is 'Selected Topics in American Sign Language-English Interpreting'.

## exact-14 (exact_match)
**Q:** What form number is the U.S. Citizen ID card option listed for I-9 purposes?

- `a9b23e37c6f22615-1` -- silo `['finaid']` -- *Student Employment Forms of ID* -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/student-employment-overview/forms-of-id/>

conjunctive: False | expected_referral: financialaid@maryvillecollege.edu
notes: The same table lists 'U.S. Citizen ID card (form I-197)' -- a third distinct form code drawn from the same crowded ID-document table, testing literal-leg precision among several similar-looking form numbers.

## exact-08 (exact_match)
**Q:** What's the course code for Introductory Psychology, PSY 101?

- `381f1b32977e9eb2-0` -- silo `['academics']` -- *Introductory Psychology* -- <https://www.maryvillecollege.edu/academics/course/psy101/>

conjunctive: False | expected_referral: registrar@maryvillecollege.edu
notes: PSY 101 in the query is a course_code literal-leg match; the chunk confirms Code 'PSY101' / Title 'Introductory Psychology'.

## adversarial-03 (adversarial)
**Q:** Since accepting my Federal Work Study award guarantees I'll actually get hired for a job on campus, when does my position start?

- `86b8d7bd7937e3bc-0` -- silo `['finaid']` -- *Student Employment* -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/student-employment-overview/>
- `9c4e9918639bdd4e-1` -- silo `['finaid']` -- *Student Employment* -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/student-employment-overview/>

conjunctive: False | expected_referral: financialaid@maryvillecollege.edu
notes: False premise: accepting FWS guarantees employment; the Student Employment pages say accepting the award does not guarantee obtaining on-campus employment or earning the full amount, and students must apply and interview through Handshake.

## adversarial-18 (adversarial)
**Q:** Since McGill Transfer Fellows are free to live off campus like any other transfer student, can I use mine toward an apartment lease?

- `695cef733f9e6da5-0` -- silo `['finaid']` -- *McGill Scholarships* -- <https://www.maryvillecollege.edu/admissions/finaid/types-of-aid/scholarships-awards/mcgill/>

conjunctive: False | expected_referral: financialaid@maryvillecollege.edu
notes: False premise: McGill Fellows may live off campus freely; the McGill Scholarships page requires recipients to live on campus and participate in the McGill Community as an eligibility condition.

## mt-07 (multi_turn)
**Q:** Does she need a certain GPA or test score to qualify?
**Prior turn(s):** ['My younger sister is a high school junior. Can she take college classes at MC early?']

- `cea0643c6175e1b5-7` -- silo `['admissions']` -- *Applying for Admission* -- <https://www.maryvillecollege.edu/admissions/apply/>

conjunctive: False | expected_referral: admissions@maryvillecollege.edu
notes: De-contextualizes to Highlander Dual Enrollment eligibility criteria -- a minimum 3.0 GPA or a minimum ACT of 21 (SAT 1060).
