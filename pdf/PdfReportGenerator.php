<?php

declare(strict_types=1);

final class PdfReportGenerator
{
    private const DPI = 150;
    private const PAGE_WIDTH_PX = 1240;
    private const PAGE_HEIGHT_PX = 1754;
    private const MARGIN_PX = 90;
    private const FOOTER_HEIGHT_PX = 70;

    private string $storageDir;
    private string $fontRegular;
    private string $fontBold;
    private string $appName;

    public function __construct(string $storageDir, string $fontRegular, string $fontBold, string $appName = 'SamurAI')
    {
        $this->storageDir = $storageDir;
        $this->fontRegular = $this->resolveFont($fontRegular, 'PDF_FONT_REGULAR');
        $this->fontBold = $this->resolveFont($fontBold, 'PDF_FONT_BOLD');
        $this->appName = $appName;
    }

    /**
     * @param array<string, mixed> $report
     * @param array<string, mixed> $profile
     * @param array<string, mixed>|null $tariffPolicy
     * @return array{path: string, filename: string}
     */
    public function generate(array $report, array $profile, ?array $tariffPolicy): array
    {
        $this->ensureStorageDir();
        $timestamp = (new DateTimeImmutable())->format('Ymd_His');
        $baseName = sprintf('report_%d_%s', (int) ($report['id'] ?? 0), $timestamp);
        $pdfPath = rtrim($this->storageDir, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . $baseName . '.pdf';

        $pages = [];
        $tempImages = [];

        $cover = $this->createPageCanvas();
        $this->renderCoverPage($cover, $report, $profile, $tariffPolicy);
        $coverPath = $this->savePageImage($cover, $baseName . '_cover.jpg');
        $pages[] = $coverPath;
        $tempImages[] = $coverPath;

        $contentPages = $this->renderContentPages($report, $profile);
        foreach ($contentPages as $pagePath) {
            $pages[] = $pagePath;
            $tempImages[] = $pagePath;
        }

        $this->applyFooters($pages);

        $writer = new SimplePdfImageWriter();
        foreach ($pages as $pagePath) {
            [$widthPx, $heightPx] = getimagesize($pagePath) ?: [self::PAGE_WIDTH_PX, self::PAGE_HEIGHT_PX];
            $widthPt = $widthPx * 72 / self::DPI;
            $heightPt = $heightPx * 72 / self::DPI;
            $writer->addImagePage($pagePath, $widthPx, $heightPx, $widthPt, $heightPt);
        }

        $writer->output($pdfPath);

        foreach ($tempImages as $tempImage) {
            @unlink($tempImage);
        }

        return [
            'path' => $pdfPath,
            'filename' => $baseName . '.pdf',
        ];
    }

    private function ensureStorageDir(): void
    {
        if (!is_dir($this->storageDir)) {
            mkdir($this->storageDir, 0775, true);
        }
    }

    private function resolveFont(string $path, string $envKey): string
    {
        if (is_file($path)) {
            return $path;
        }

        throw new RuntimeException(
            sprintf('Не найден файл шрифта: %s. Укажите корректный путь через %s.', $path, $envKey)
        );
    }

    /** @return resource */
    private function createPageCanvas()
    {
        $image = imagecreatetruecolor(self::PAGE_WIDTH_PX, self::PAGE_HEIGHT_PX);
        $white = imagecolorallocate($image, 255, 255, 255);
        imagefilledrectangle($image, 0, 0, self::PAGE_WIDTH_PX, self::PAGE_HEIGHT_PX, $white);
        return $image;
    }

    /**
     * @param resource $image
     * @param array<string, mixed> $report
     * @param array<string, mixed> $profile
     * @param array<string, mixed>|null $tariffPolicy
     */
    private function renderCoverPage($image, array $report, array $profile, ?array $tariffPolicy): void
    {
        $black = imagecolorallocate($image, 20, 20, 20);
        $centerX = (int) (self::PAGE_WIDTH_PX / 2);

        $title = 'Нумерологический отчёт';
        $this->drawCenteredText($image, $title, 38, $centerX, 260, $black, $this->fontBold);

        $name = (string) ($profile['birth_name'] ?? '—');
        $tariff = $tariffPolicy['title'] ?? null;
        $tariffText = $tariff ? sprintf('Тариф: %s', $tariff) : sprintf('Тариф: %s', $report['tariff_id'] ?? '—');

        $createdAt = (string) ($report['created_at'] ?? '');
        $dateText = $this->formatDate($createdAt);

        $this->drawCenteredText($image, 'ФИО при рождении', 20, $centerX, 420, $black, $this->fontBold);
        $this->drawCenteredText($image, $name, 26, $centerX, 470, $black, $this->fontRegular);

        $this->drawCenteredText($image, $tariffText, 20, $centerX, 560, $black, $this->fontRegular);
        $this->drawCenteredText($image, 'Дата формирования: ' . $dateText, 20, $centerX, 610, $black, $this->fontRegular);
    }

    /**
     * @param array<string, mixed> $report
     * @param array<string, mixed> $profile
     * @return array<int, string>
     */
    private function renderContentPages(array $report, array $profile): array
    {
        $pages = [];
        $blocks = $this->extractBlocks($report);
        $disclaimer = $this->extractDisclaimer($report);

        if ($disclaimer !== null && $disclaimer !== '') {
            $blocks[] = ['type' => 'h2', 'value' => 'Дисклеймер'];
            $blocks[] = ['type' => 'p', 'value' => $disclaimer];
        }

        $currentPage = $this->createPageCanvas();
        $cursorY = self::MARGIN_PX;
        $availableHeight = self::PAGE_HEIGHT_PX - self::FOOTER_HEIGHT_PX - self::MARGIN_PX;

        $black = imagecolorallocate($currentPage, 20, 20, 20);

        foreach ($blocks as $block) {
            $blockLines = $this->renderBlockLines($block);
            $lineHeight = $blockLines['line_height'];
            $lines = $blockLines['lines'];
            $font = $blockLines['font'];
            $fontSize = $blockLines['font_size'];

            foreach ($lines as $line) {
                if ($cursorY + $lineHeight > $availableHeight) {
                    $pages[] = $this->savePageImage($currentPage, uniqid('page_', true) . '.jpg');
                    imagedestroy($currentPage);
                    $currentPage = $this->createPageCanvas();
                    $black = imagecolorallocate($currentPage, 20, 20, 20);
                    $cursorY = self::MARGIN_PX;
                }

                $this->drawTextLine(
                    $currentPage,
                    $line,
                    $fontSize,
                    self::MARGIN_PX,
                    $cursorY,
                    $black,
                    $font
                );
                $cursorY += $lineHeight;
            }

            $cursorY += (int) ($lineHeight * 0.4);
        }

        $pages[] = $this->savePageImage($currentPage, uniqid('page_', true) . '.jpg');
        imagedestroy($currentPage);

        return $pages;
    }

    private function formatDate(string $value): string
    {
        if ($value === '') {
            return '—';
        }

        try {
            $date = new DateTimeImmutable($value);
        } catch (Exception) {
            return '—';
        }

        return $date->format('d.m.Y');
    }

    /**
     * @param array<string, mixed> $report
     * @return array<int, array<string, mixed>>
     */
    private function extractBlocks(array $report): array
    {
        $reportJson = $report['report_json'] ?? null;
        if (is_string($reportJson) && $reportJson !== '') {
            $decoded = json_decode($reportJson, true);
            if (is_array($decoded) && isset($decoded['pdf_blocks']) && is_array($decoded['pdf_blocks'])) {
                return $decoded['pdf_blocks'];
            }
        }

        $text = (string) ($report['report_text'] ?? '');
        return $this->plainTextToBlocks($text);
    }

    /**
     * @param array<string, mixed> $report
     */
    private function extractDisclaimer(array $report): ?string
    {
        $reportJson = $report['report_json'] ?? null;
        if (!is_string($reportJson) || $reportJson === '') {
            return null;
        }

        $decoded = json_decode($reportJson, true);
        if (is_array($decoded) && isset($decoded['disclaimer']) && is_string($decoded['disclaimer'])) {
            return $decoded['disclaimer'];
        }

        return null;
    }

    /**
     * @return array{lines: array<int, string>, line_height: int, font_size: int, font: string}
     * @param array<string, mixed> $block
     */
    private function renderBlockLines(array $block): array
    {
        $type = (string) ($block['type'] ?? 'p');
        $font = $this->fontRegular;
        $fontSize = 22;

        if ($type === 'h1') {
            $font = $this->fontBold;
            $fontSize = 30;
        } elseif ($type === 'h2') {
            $font = $this->fontBold;
            $fontSize = 26;
        } elseif ($type === 'h3') {
            $font = $this->fontBold;
            $fontSize = 24;
        }

        if ($type === 'ul' && isset($block['items']) && is_array($block['items'])) {
            $lines = [];
            foreach ($block['items'] as $item) {
                $wrapped = $this->wrapText('• ' . (string) $item, $font, $fontSize);
                foreach ($wrapped as $line) {
                    $lines[] = $line;
                }
            }

            return [
                'lines' => $lines,
                'line_height' => (int) ($fontSize * 1.5),
                'font_size' => $fontSize,
                'font' => $font,
            ];
        }

        $value = (string) ($block['value'] ?? '');
        $lines = $this->wrapText($value, $font, $fontSize);

        return [
            'lines' => $lines,
            'line_height' => (int) ($fontSize * 1.5),
            'font_size' => $fontSize,
            'font' => $font,
        ];
    }

    /**
     * @return array<int, array<string, string>>
     */
    private function plainTextToBlocks(string $text): array
    {
        $normalized = trim($text);
        if ($normalized === '') {
            return [['type' => 'p', 'value' => 'Отчёт пока пуст.']];
        }

        $paragraphs = preg_split('/\n\s*\n/u', $normalized) ?: [];
        $blocks = [];
        foreach ($paragraphs as $paragraph) {
            $paragraph = trim($paragraph);
            if ($paragraph === '') {
                continue;
            }

            $blocks[] = [
                'type' => 'p',
                'value' => $paragraph,
            ];
        }

        return $blocks;
    }

    /**
     * @param resource $image
     */
    private function drawCenteredText($image, string $text, int $fontSize, int $centerX, int $baselineY, int $color, string $fontPath): void
    {
        $box = imagettfbbox($fontSize, 0, $fontPath, $text);
        if ($box === false) {
            return;
        }

        $textWidth = (int) ($box[2] - $box[0]);
        $x = $centerX - (int) ($textWidth / 2);

        imagettftext($image, $fontSize, 0, $x, $baselineY, $color, $fontPath, $text);
    }

    /**
     * @param resource $image
     */
    private function drawTextLine($image, string $text, int $fontSize, int $x, int $baselineY, int $color, string $fontPath): void
    {
        imagettftext($image, $fontSize, 0, $x, $baselineY, $color, $fontPath, $text);
    }

    /**
     * @return array<int, string>
     */
    private function wrapText(string $text, string $fontPath, int $fontSize): array
    {
        $maxWidth = self::PAGE_WIDTH_PX - (self::MARGIN_PX * 2);
        $words = preg_split('/\s+/u', $text) ?: [];
        $lines = [];
        $current = '';

        foreach ($words as $word) {
            $candidate = $current === '' ? $word : $current . ' ' . $word;
            $box = imagettfbbox($fontSize, 0, $fontPath, $candidate);
            if ($box === false) {
                $lines[] = $candidate;
                $current = '';
                continue;
            }

            $width = $box[2] - $box[0];
            if ($width > $maxWidth && $current !== '') {
                $lines[] = $current;
                $current = $word;
            } else {
                $current = $candidate;
            }
        }

        if ($current !== '') {
            $lines[] = $current;
        }

        return $lines;
    }

    /**
     * @param array<int, string> $pages
     */
    private function applyFooters(array $pages): void
    {
        $total = count($pages);
        foreach ($pages as $index => $pagePath) {
            $image = imagecreatefromjpeg($pagePath);
            if ($image === false) {
                continue;
            }

            $footerText = sprintf('%s — стр. %d из %d', $this->appName, $index + 1, $total);
            $color = imagecolorallocate($image, 80, 80, 80);
            $fontSize = 18;
            $baseline = self::PAGE_HEIGHT_PX - (int) (self::FOOTER_HEIGHT_PX / 2);
            $this->drawCenteredText($image, $footerText, $fontSize, (int) (self::PAGE_WIDTH_PX / 2), $baseline, $color, $this->fontRegular);

            imagejpeg($image, $pagePath, 85);
            imagedestroy($image);
        }
    }

    /**
     * @param resource $image
     */
    private function savePageImage($image, string $filename): string
    {
        $path = rtrim($this->storageDir, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . $filename;
        imagejpeg($image, $path, 85);
        return $path;
    }
}
