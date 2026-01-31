<?php

declare(strict_types=1);

final class StatsService
{
    private PDO $pdo;
    private DateTimeZone $statsTimezone;

    public function __construct(PDO $pdo, DateTimeZone $statsTimezone)
    {
        $this->pdo = $pdo;
        $this->statsTimezone = $statsTimezone;
    }

    /**
     * @return array<int, array<string, int|float|string>>
     */
    public function buildDailyStats(DateTimeImmutable $startDate, DateTimeImmutable $endDate): array
    {
        $stats = [];
        $current = $startDate;

        while ($current <= $endDate) {
            $dayStart = $current->setTimezone($this->statsTimezone)->setTime(0, 0);
            $dayEnd = $dayStart->modify('+1 day');

            $startUtc = $dayStart->setTimezone(new DateTimeZone('UTC'))->format('c');
            $endUtc = $dayEnd->setTimezone(new DateTimeZone('UTC'))->format('c');

            $stats[] = [
                'date' => $dayStart->format('Y-m-d'),
                'new_users' => $this->countByDateRange('users', 'created_at', $startUtc, $endUtc),
                'started_form' => $this->countMessagesByType('system_event', 'started_form', $startUtc, $endUtc),
                'finished_form' => $this->countMessagesByType('system_event', 'finished_form', $startUtc, $endUtc),
                'reports_generated' => $this->countByDateRange('reports', 'created_at', $startUtc, $endUtc),
                'pdf_downloads' => $this->countMessagesByType('system_event', 'pdf_downloaded', $startUtc, $endUtc),
                'followup_questions' => $this->countFollowupQuestions($startUtc, $endUtc),
                'bought_users' => $this->countPaidUsers($startUtc, $endUtc),
                'revenue' => $this->sumPaidRevenue($startUtc, $endUtc),
            ];

            $current = $current->modify('+1 day');
        }

        return $stats;
    }

    private function countByDateRange(string $table, string $column, string $start, string $end): int
    {
        $stmt = $this->pdo->prepare(
            sprintf('SELECT COUNT(*) FROM %s WHERE %s >= :start AND %s < :end', $table, $column, $column)
        );
        $stmt->execute(['start' => $start, 'end' => $end]);

        return (int) $stmt->fetchColumn();
    }

    private function countMessagesByType(string $type, string $text, string $start, string $end): int
    {
        $stmt = $this->pdo->prepare(
            'SELECT COUNT(*) FROM messages WHERE message_type = :type AND text = :text AND created_at >= :start AND created_at < :end'
        );
        $stmt->execute([
            'type' => $type,
            'text' => $text,
            'start' => $start,
            'end' => $end,
        ]);

        return (int) $stmt->fetchColumn();
    }

    private function countFollowupQuestions(string $start, string $end): int
    {
        $stmt = $this->pdo->prepare(
            'SELECT COUNT(*) FROM messages WHERE message_type = :type AND direction = :direction AND created_at >= :start AND created_at < :end'
        );
        $stmt->execute([
            'type' => 'followup',
            'direction' => 'in',
            'start' => $start,
            'end' => $end,
        ]);

        return (int) $stmt->fetchColumn();
    }

    private function countPaidUsers(string $start, string $end): int
    {
        $stmt = $this->pdo->prepare(
            'SELECT COUNT(DISTINCT user_id) FROM purchases WHERE status = :status AND COALESCE(paid_at, created_at) >= :start AND COALESCE(paid_at, created_at) < :end'
        );
        $stmt->execute([
            'status' => 'paid',
            'start' => $start,
            'end' => $end,
        ]);

        return (int) $stmt->fetchColumn();
    }

    private function sumPaidRevenue(string $start, string $end): float
    {
        $stmt = $this->pdo->prepare(
            'SELECT COALESCE(SUM(amount), 0) FROM purchases WHERE status = :status AND COALESCE(paid_at, created_at) >= :start AND COALESCE(paid_at, created_at) < :end'
        );
        $stmt->execute([
            'status' => 'paid',
            'start' => $start,
            'end' => $end,
        ]);

        return (float) $stmt->fetchColumn();
    }
}
