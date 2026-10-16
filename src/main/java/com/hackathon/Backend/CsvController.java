
package com.hackathon.Backend;

import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/csv")
public class CsvController {

    private final CsvService csvService;

    public CsvController(CsvService csvService) {
        this.csvService = csvService;
    }

    @GetMapping
    public List<CsvService.FileInfo> listFiles() {
        return csvService.listFiles();
    }

    @GetMapping("/{filename:.+}")
    public CsvService.CsvPage getCsv(
            @PathVariable String filename,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "50") int size,
            @RequestParam(defaultValue = "") String search
    ) {
        return csvService.getPage(filename, page, size, search);
    }
}
