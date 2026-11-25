<?php
// Test data for the CBT compatibility VM test: a module, a subject with two
// single-answer questions, a test open for a year, a group and a student
// (student1 / Student-Test-1) in it. Idempotent; earlier attempts are cleared. Prints the test's id.
$db = new PDO('pgsql:host=127.0.0.1;dbname=tcexam', 'tcexam', $argv[1],
              [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$one = function ($sql, $args = []) use ($db) {
    $st = $db->prepare($sql);
    $st->execute($args);
    return $st->columnCount() ? $st->fetchColumn() : null;
};
$id = $one("SELECT test_id FROM tce_tests WHERE test_name = 'CSC 101 test'");
if ($id) {
    // Each run takes the test afresh (it isn't repeatable): clear earlier attempts
    $attempts = "SELECT testuser_id FROM tce_tests_users WHERE testuser_test_id = ?";
    $one("DELETE FROM tce_tests_logs_answers WHERE logansw_testlog_id IN
          (SELECT testlog_id FROM tce_tests_logs WHERE testlog_testuser_id IN ($attempts))", [$id]);
    $one("DELETE FROM tce_tests_logs WHERE testlog_testuser_id IN ($attempts)", [$id]);
    $one("DELETE FROM tce_tests_users WHERE testuser_test_id = ?", [$id]);
    echo $id, "\n";
    exit(0);
}
$db->beginTransaction();
$module = $one("INSERT INTO tce_modules (module_name, module_enabled) VALUES ('CSC 101', true) RETURNING module_id");
$subject = $one("INSERT INTO tce_subjects (subject_module_id, subject_name, subject_description, subject_enabled)
                 VALUES (?, 'Basics', 'Computing basics', true) RETURNING subject_id", [$module]);
foreach ([['What does CPU stand for?', ['Central Processing Unit', 'Computer Personal Unit']],
          ['What does RAM stand for?', ['Random Access Memory', 'Read Any Memory']]] as $i => [$text, $answers]) {
    $q = $one("INSERT INTO tce_questions (question_subject_id, question_description, question_type,
               question_difficulty, question_enabled, question_position) VALUES (?, ?, 1, 1, true, ?)
               RETURNING question_id", [$subject, $text, $i + 1]);
    foreach ($answers as $j => $a) {
        $one("INSERT INTO tce_answers (answer_question_id, answer_description, answer_isright, answer_enabled,
              answer_position) VALUES (?, ?, ?, true, ?) RETURNING answer_id", [$q, $a, $j == 0 ? 'true' : 'false', $j + 1]);
    }
}
$test = $one("INSERT INTO tce_tests (test_name, test_description, test_begin_time, test_end_time,
              test_duration_time, test_ip_range, test_max_score, test_score_right, test_results_to_users)
              VALUES ('CSC 101 test', 'Two questions', now() - interval '1 day', now() + interval '365 days',
              30, '*.*.*.*', 2, 1, true) RETURNING test_id");
$set = $one("INSERT INTO tce_test_subject_set (tsubset_test_id, tsubset_type, tsubset_difficulty,
             tsubset_quantity, tsubset_answers) VALUES (?, 1, 1, 2, 2) RETURNING tsubset_id", [$test]);
$one("INSERT INTO tce_test_subjects (subjset_tsubset_id, subjset_subject_id) VALUES (?, ?)", [$set, $subject]);
$group = $one("INSERT INTO tce_user_groups (group_name) VALUES ('CSC 101 class') RETURNING group_id");
$user = $one("INSERT INTO tce_users (user_regdate, user_ip, user_name, user_password, user_firstname,
              user_lastname, user_level) VALUES (now(), '0.0.0.0', 'student1', ?, 'Ada', 'Okafor', 1)
              RETURNING user_id", [password_hash('Student-Test-1', PASSWORD_DEFAULT)]);
$one("INSERT INTO tce_usrgroups (usrgrp_user_id, usrgrp_group_id) VALUES (?, ?)", [$user, $group]);
$one("INSERT INTO tce_testgroups (tstgrp_test_id, tstgrp_group_id) VALUES (?, ?)", [$test, $group]);
$db->commit();
echo $test, "\n";
