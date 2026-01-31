<?php

declare(strict_types=1);

abstract class AbstractRepository
{
    protected PDO $pdo;
    protected string $table;
    /** @var string[] */
    protected array $columns = [];

    public function __construct(PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    /** @param array<string, mixed> $data */
    public function insert(array $data): int
    {
        $filtered = $this->filterData($data);
        if ($filtered === []) {
            throw new InvalidArgumentException('No valid columns provided for insert.');
        }

        $columns = array_keys($filtered);
        $placeholders = array_map(static fn(string $col) => ':' . $col, $columns);

        $sql = sprintf(
            'INSERT INTO %s (%s) VALUES (%s)',
            $this->table,
            implode(', ', $columns),
            implode(', ', $placeholders)
        );

        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($filtered);

        return (int) $this->pdo->lastInsertId();
    }

    /** @return array<string, mixed>|null */
    public function findById(int $id): ?array
    {
        $stmt = $this->pdo->prepare(sprintf('SELECT * FROM %s WHERE id = :id', $this->table));
        $stmt->execute(['id' => $id]);
        $result = $stmt->fetch();

        return $result === false ? null : $result;
    }

    /** @return array<int, array<string, mixed>> */
    public function findAll(): array
    {
        $stmt = $this->pdo->query(sprintf('SELECT * FROM %s', $this->table));

        return $stmt === false ? [] : $stmt->fetchAll();
    }

    public function countAll(): int
    {
        $stmt = $this->pdo->query(sprintf('SELECT COUNT(*) FROM %s', $this->table));
        if ($stmt === false) {
            return 0;
        }

        return (int) $stmt->fetchColumn();
    }

    /** @return array<string, mixed>|null */
    public function findOneBy(string $column, mixed $value): ?array
    {
        $this->assertColumnAllowed($column);

        $stmt = $this->pdo->prepare(
            sprintf('SELECT * FROM %s WHERE %s = :value LIMIT 1', $this->table, $column)
        );
        $stmt->execute(['value' => $value]);
        $result = $stmt->fetch();

        return $result === false ? null : $result;
    }

    /** @return array<int, array<string, mixed>> */
    public function findAllBy(string $column, mixed $value): array
    {
        $this->assertColumnAllowed($column);

        $stmt = $this->pdo->prepare(
            sprintf('SELECT * FROM %s WHERE %s = :value', $this->table, $column)
        );
        $stmt->execute(['value' => $value]);

        return $stmt->fetchAll();
    }

    /** @param array<string, mixed> $data */
    public function update(int $id, array $data): void
    {
        $filtered = $this->filterData($data);
        if ($filtered === []) {
            return;
        }

        $sets = [];
        foreach (array_keys($filtered) as $column) {
            $sets[] = sprintf('%s = :%s', $column, $column);
        }

        $filtered['id'] = $id;

        $sql = sprintf('UPDATE %s SET %s WHERE id = :id', $this->table, implode(', ', $sets));
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($filtered);
    }

    /** @param array<string, mixed> $data */
    protected function filterData(array $data): array
    {
        return array_intersect_key($data, array_flip($this->columns));
    }

    protected function assertColumnAllowed(string $column): void
    {
        if (!in_array($column, $this->columns, true)) {
            throw new InvalidArgumentException(sprintf('Column "%s" is not allowed for %s.', $column, $this->table));
        }
    }
}
