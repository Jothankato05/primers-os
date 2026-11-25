<?php
// Test data for the CBT compatibility VM test: a course, a student
// (student1 / Student-Test-1), and a quiz with two questions. Idempotent.
// Prints the quiz's course-module id.
define('CLI_SCRIPT', true);
require($argv[1] . '/config.php');
require_once($CFG->libdir . '/testing/generator/lib.php');
require_once($CFG->dirroot . '/mod/quiz/locallib.php');

$gen = new testing_data_generator();
\core\session\manager::set_user(get_admin());
// The login form takes the keyboard straight away (a common site setting;
// the VM test signs in by typing)
set_config('loginpageautofocus', 1);

$course = $DB->get_record('course', ['shortname' => 'CSC101']);
if (!$course) {
    $course = $gen->create_course(['fullname' => 'CSC 101 Introduction to Computing', 'shortname' => 'CSC101']);
}
$student = $DB->get_record('user', ['username' => 'student1']);
if (!$student) {
    $student = $gen->create_user(['username' => 'student1', 'password' => 'Student-Test-1',
                                  'firstname' => 'Ada', 'lastname' => 'Okafor']);
}
$gen->enrol_user($student->id, $course->id, 'student');
// The course index and block drawers closed (a per-user choice Moodle
// remembers): the VM test finds the page's buttons by their colour, and
// the selected course-index entry is the same blue
set_user_preference('drawer-open-index', 0, $student);
set_user_preference('drawer-open-block', 0, $student);

$cm = $DB->get_record_sql("SELECT cm.id FROM {course_modules} cm JOIN {modules} m ON m.id = cm.module
                           JOIN {quiz} q ON q.id = cm.instance
                           WHERE m.name = 'quiz' AND cm.course = ? AND q.name = ?", [$course->id, 'CSC 101 test']);
if (!$cm) {
    $quiz = $gen->get_plugin_generator('mod_quiz')->create_instance([
        'course' => $course->id, 'name' => 'CSC 101 test', 'questionsperpage' => 0,
        'grade' => 10, 'sumgrades' => 2, 'navmethod' => 'free']);
    $cm = (object)['id' => $quiz->cmid];
}
$quiz = $DB->get_record('quiz', ['id' => $DB->get_field('course_modules', 'instance', ['id' => $cm->id])]);
$quiz->cmid = $cm->id;
if (!$DB->record_exists('quiz_slots', ['quizid' => $quiz->id])) {
    // Questions the way a teacher adds them in bulk: a GIFT file through
    // Moodle's importer (the test generators for questions need PHPUnit)
    $context = context_course::instance($course->id);
    $cat = $gen->get_plugin_generator('core_question')->create_question_category(['contextid' => $context->id]);
    $gift = tempnam(sys_get_temp_dir(), 'gift');
    file_put_contents($gift, "::CPU::CPU stands for Central Processing Unit.{TRUE}\n\n" .
                             "::RAM::What does RAM stand for?{=Random Access Memory =random access memory}\n");
    require_once($CFG->dirroot . '/question/format.php');
    require_once($CFG->dirroot . '/question/format/gift/format.php');
    $format = new qformat_gift();
    $format->setCategory($cat);
    $format->setContexts([$context]);
    $format->setCourse($course);
    $format->setFilename($gift);
    $format->setRealfilename('questions.gift');
    $format->setMatchgrades('error');
    $format->setCatfromfile(false);
    $format->setContextfromfile(false);
    $format->setStoponerror(true);
    ob_start();
    $ok = $format->importpreprocess() && $format->importprocess() && $format->importpostprocess();
    ob_end_clean();
    unlink($gift);
    if (!$ok || count($format->questionids) != 2) {
        throw new moodle_exception('question import failed');
    }
    foreach ($format->questionids as $qid) {
        quiz_add_quiz_question($qid, $quiz);
    }
    quiz_update_sumgrades($quiz);
}
echo $cm->id, "\n";
