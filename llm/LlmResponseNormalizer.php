<?php

declare(strict_types=1);

final class LlmResponseNormalizer
{
    /**
     * @param array<string, int>|null $usage
     * @param callable(string): ?string|null $repairCallback
     */
    public function normalize(
        string $provider,
        string $model,
        string $rawText,
        ?array $usage,
        int $latencyMs,
        ?string $requestId,
        ?callable $repairCallback = null
    ): LlmResult {
        $parsedJson = $this->parseJsonFromText($rawText);
        if ($parsedJson === null && $repairCallback !== null) {
            $repairedText = $repairCallback($rawText);
            if (is_string($repairedText) && $repairedText !== '') {
                $parsedJson = $this->parseJsonFromText($repairedText);
            }
        }

        $text = $this->extractText($rawText, $parsedJson);
        $pdfBlocks = $this->extractPdfBlocks($parsedJson);
        $disclaimer = $this->extractDisclaimer($parsedJson);

        return new LlmResult(
            $provider,
            $model,
            $rawText,
            $parsedJson,
            $text,
            $pdfBlocks,
            $disclaimer,
            $usage,
            $latencyMs,
            $requestId
        );
    }

    /** @return array<string, mixed>|null */
    private function parseJsonFromText(string $rawText): ?array
    {
        $candidate = $this->extractJsonCandidate($rawText);
        if ($candidate === null) {
            return null;
        }

        $decoded = json_decode($candidate, true);
        if (json_last_error() !== JSON_ERROR_NONE || !is_array($decoded)) {
            return null;
        }

        return $decoded;
    }

    private function extractJsonCandidate(string $rawText): ?string
    {
        $trimmed = trim($rawText);
        if ($trimmed === '') {
            return null;
        }

        if (preg_match('/```(?:json)?\s*(\{.*\}|\[.*\])\s*```/su', $rawText, $matches)) {
            return $matches[1];
        }

        $firstBrace = strpos($rawText, '{');
        $lastBrace = strrpos($rawText, '}');
        if ($firstBrace !== false && $lastBrace !== false && $lastBrace > $firstBrace) {
            return substr($rawText, $firstBrace, $lastBrace - $firstBrace + 1);
        }

        $firstBracket = strpos($rawText, '[');
        $lastBracket = strrpos($rawText, ']');
        if ($firstBracket !== false && $lastBracket !== false && $lastBracket > $firstBracket) {
            return substr($rawText, $firstBracket, $lastBracket - $firstBracket + 1);
        }

        return null;
    }

    /**
     * @param array<string, mixed>|null $parsedJson
     */
    private function extractText(string $rawText, ?array $parsedJson): string
    {
        if ($parsedJson !== null && isset($parsedJson['text']) && is_string($parsedJson['text'])) {
            return $parsedJson['text'];
        }

        return trim($rawText);
    }

    /**
     * @param array<string, mixed>|null $parsedJson
     * @return array<int, array<string, mixed>>|null
     */
    private function extractPdfBlocks(?array $parsedJson): ?array
    {
        if ($parsedJson !== null && isset($parsedJson['pdf_blocks']) && is_array($parsedJson['pdf_blocks'])) {
            return $parsedJson['pdf_blocks'];
        }

        return null;
    }

    /**
     * @param array<string, mixed>|null $parsedJson
     */
    private function extractDisclaimer(?array $parsedJson): ?string
    {
        if ($parsedJson !== null && isset($parsedJson['disclaimer']) && is_string($parsedJson['disclaimer'])) {
            return $parsedJson['disclaimer'];
        }

        return null;
    }
}
