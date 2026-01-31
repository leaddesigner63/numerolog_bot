<?php

declare(strict_types=1);

final class LlmResult
{
    private string $provider;
    private string $model;
    private string $rawText;
    /** @var array<string, mixed>|null */
    private ?array $parsedJson;
    private string $text;
    /** @var array<int, array<string, mixed>>|null */
    private ?array $pdfBlocks;
    private ?string $disclaimer;
    /** @var array<string, int>|null */
    private ?array $usage;
    private int $latencyMs;
    private ?string $requestId;

    /**
     * @param array<string, mixed>|null $parsedJson
     * @param array<int, array<string, mixed>>|null $pdfBlocks
     * @param array<string, int>|null $usage
     */
    public function __construct(
        string $provider,
        string $model,
        string $rawText,
        ?array $parsedJson,
        string $text,
        ?array $pdfBlocks,
        ?string $disclaimer,
        ?array $usage,
        int $latencyMs,
        ?string $requestId
    ) {
        $this->provider = $provider;
        $this->model = $model;
        $this->rawText = $rawText;
        $this->parsedJson = $parsedJson;
        $this->text = $text;
        $this->pdfBlocks = $pdfBlocks;
        $this->disclaimer = $disclaimer;
        $this->usage = $usage;
        $this->latencyMs = $latencyMs;
        $this->requestId = $requestId;
    }

    public function getProvider(): string
    {
        return $this->provider;
    }

    public function getModel(): string
    {
        return $this->model;
    }

    public function getRawText(): string
    {
        return $this->rawText;
    }

    /** @return array<string, mixed>|null */
    public function getParsedJson(): ?array
    {
        return $this->parsedJson;
    }

    public function getText(): string
    {
        return $this->text;
    }

    /** @return array<int, array<string, mixed>>|null */
    public function getPdfBlocks(): ?array
    {
        return $this->pdfBlocks;
    }

    public function getDisclaimer(): ?string
    {
        return $this->disclaimer;
    }

    /** @return array<string, int>|null */
    public function getUsage(): ?array
    {
        return $this->usage;
    }

    public function getLatencyMs(): int
    {
        return $this->latencyMs;
    }

    public function getRequestId(): ?string
    {
        return $this->requestId;
    }

    /** @return array<string, mixed> */
    public function toArray(): array
    {
        return [
            'provider' => $this->provider,
            'model' => $this->model,
            'raw_text' => $this->rawText,
            'parsed_json' => $this->parsedJson,
            'text' => $this->text,
            'pdf_blocks' => $this->pdfBlocks,
            'disclaimer' => $this->disclaimer,
            'usage' => $this->usage,
            'latency_ms' => $this->latencyMs,
            'request_id' => $this->requestId,
        ];
    }
}
