<?php

declare(strict_types=1);

final class SimplePdfImageWriter
{
    /** @var array<int, array{path: string, width_px: int, height_px: int, width_pt: float, height_pt: float}> */
    private array $pages = [];

    public function addImagePage(string $path, int $widthPx, int $heightPx, float $widthPt, float $heightPt): void
    {
        $this->pages[] = [
            'path' => $path,
            'width_px' => $widthPx,
            'height_px' => $heightPx,
            'width_pt' => $widthPt,
            'height_pt' => $heightPt,
        ];
    }

    public function output(string $filePath): void
    {
        $objects = [];
        $pageCount = count($this->pages);
        $pagesObjNumber = ($pageCount * 3) + 1;
        $catalogObjNumber = $pagesObjNumber + 1;

        for ($index = 0; $index < $pageCount; $index++) {
            $page = $this->pages[$index];
            $imageData = file_get_contents($page['path']);
            if ($imageData === false) {
                throw new RuntimeException(sprintf('Unable to read image %s', $page['path']));
            }

            $objects[] = $this->buildImageObject($page, $imageData);
        }

        for ($index = 0; $index < $pageCount; $index++) {
            $page = $this->pages[$index];
            $contentStream = $this->buildContentStream($page);
            $objects[] = $this->buildStreamObject($contentStream);
        }

        $pageObjectNumbers = [];
        for ($index = 0; $index < $pageCount; $index++) {
            $imageObject = $index + 1;
            $contentObject = $pageCount + $index + 1;
            $pageObject = ($pageCount * 2) + $index + 1;
            $pageObjectNumbers[] = $pageObject;
            $objects[] = $this->buildPageObject(
                $this->pages[$index],
                $imageObject,
                $contentObject,
                $pagesObjNumber
            );
        }

        $pagesKids = array_map(
            static fn(int $pageObject): string => sprintf('%d 0 R', $pageObject),
            $pageObjectNumbers
        );

        $objects[] = sprintf(
            "<< /Type /Pages /Kids [%s] /Count %d >>",
            implode(' ', $pagesKids),
            $pageCount
        );

        $objects[] = sprintf("<< /Type /Catalog /Pages %d 0 R >>", $pagesObjNumber);

        $pdf = "%PDF-1.4\n";
        $offsets = [];
        foreach ($objects as $index => $object) {
            $offsets[] = strlen($pdf);
            $pdf .= sprintf("%d 0 obj\n%s\nendobj\n", $index + 1, $object);
        }

        $xrefPosition = strlen($pdf);
        $pdf .= sprintf("xref\n0 %d\n", count($objects) + 1);
        $pdf .= "0000000000 65535 f \n";
        foreach ($offsets as $offset) {
            $pdf .= sprintf("%010d 00000 n \n", $offset);
        }

        $pdf .= sprintf(
            "trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%EOF",
            count($objects) + 1,
            $catalogObjNumber,
            $xrefPosition
        );

        file_put_contents($filePath, $pdf);
    }

    /**
     * @param array{width_px: int, height_px: int} $page
     */
    private function buildImageObject(array $page, string $imageData): string
    {
        return sprintf(
            "<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 "
            . "/Filter /DCTDecode /Length %d >>\nstream\n%s\nendstream",
            $page['width_px'],
            $page['height_px'],
            strlen($imageData),
            $imageData
        );
    }

    /**
     * @param array{width_pt: float, height_pt: float} $page
     */
    private function buildContentStream(array $page): string
    {
        return sprintf(
            "q\n%.2f 0 0 %.2f 0 0 cm\n/Im1 Do\nQ",
            $page['width_pt'],
            $page['height_pt']
        );
    }

    private function buildStreamObject(string $stream): string
    {
        return sprintf("<< /Length %d >>\nstream\n%s\nendstream", strlen($stream), $stream);
    }

    /**
     * @param array{width_pt: float, height_pt: float} $page
     */
    private function buildPageObject(array $page, int $imageObject, int $contentObject, int $parentObject): string
    {
        return sprintf(
            "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /XObject << /Im1 %d 0 R >> >> "
            . "/Contents %d 0 R >>",
            $parentObject,
            $page['width_pt'],
            $page['height_pt'],
            $imageObject,
            $contentObject
        );
    }
}
