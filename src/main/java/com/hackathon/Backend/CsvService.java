
package com.hackathon.Backend;

import jakarta.annotation.PostConstruct;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Stream;

@Service
public class CsvService {

    @Value("${app.csv.directory:./csvFiles}")
    private String configuredDirectory;

    private Path root;
    private final Map<String, CachedCsv> cache =
            new ConcurrentHashMap<>();

    @PostConstruct
    void initialize() throws IOException {
        root = Paths.get(configuredDirectory)
                .toAbsolutePath().normalize();
        Files.createDirectories(root);
    }

    public record FileInfo(
            String name, long sizeBytes, long lastModified
    ) {}

    public record CsvPage(
            String filename,
            List<String> headers,
            List<List<String>> rows,
            long totalRows,
            int page,
            int size,
            int totalPages
    ) {}

    private record CachedCsv(
            long modified,
            long sizeBytes,
            List<String> headers,
            List<List<String>> rows
    ) {}

    public List<FileInfo> listFiles() {
        try (Stream<Path> files = Files.list(root)) {
            return files
                    .filter(Files::isRegularFile)
                    .filter(p -> p.getFileName().toString()
                            .toLowerCase(Locale.ROOT)
                            .endsWith(".csv"))
                    .map(p -> {
                        try {
                            return new FileInfo(
                                    p.getFileName().toString(),
                                    Files.size(p),
                                    Files.getLastModifiedTime(p)
                                            .toMillis()
                            );
                        } catch (IOException e) {
                            return null;
                        }
                    })
                    .filter(Objects::nonNull)
                    .sorted(Comparator.comparing(FileInfo::name))
                    .toList();
        } catch (IOException e) {
            throw new ResponseStatusException(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "Could not list CSV files"
            );
        }
    }

    private Path safePath(String filename) {
        if (filename == null
                || !filename.toLowerCase(Locale.ROOT)
                        .endsWith(".csv")
                || !Paths.get(filename).getFileName()
                        .toString().equals(filename)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "Invalid filename"
            );
        }

        Path path = root.resolve(filename).normalize();

        if (!path.startsWith(root)
                || !Files.isRegularFile(path)) {
            throw new ResponseStatusException(
                    HttpStatus.NOT_FOUND, "CSV file not found"
            );
        }

        return path;
    }

    private CachedCsv load(String filename) {
        Path path = safePath(filename);

        try {
            long modified = Files.getLastModifiedTime(path)
                    .toMillis();
            long bytes = Files.size(path);

            CachedCsv existing = cache.get(filename);

            if (existing != null
                    && existing.modified() == modified
                    && existing.sizeBytes() == bytes) {
                return existing;
            }

            CachedCsv fresh;

            try (var reader = Files.newBufferedReader(
                    path, StandardCharsets.UTF_8);
                 var parser = CSVParser.parse(
                    reader,
                    CSVFormat.DEFAULT.builder()
                            .setHeader()
                            .setSkipHeaderRecord(true)
                            .get()
                 )) {

                List<String> headers =
                        List.copyOf(parser.getHeaderNames());

                List<List<String>> rows = parser.getRecords()
                        .stream()
                        .map(record ->
                                Collections.unmodifiableList(
                                        new ArrayList<>(
                                                record.toList()
                                        )
                                ))
                        .toList();

                fresh = new CachedCsv(
                        modified, bytes, headers, rows
                );
            }

            cache.put(filename, fresh);
            return fresh;

        } catch (IOException | IllegalArgumentException e) {
            cache.remove(filename);
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Could not read CSV file: " + filename
            );
        }
    }

    public CsvPage getPage(
            String filename, int page, int size, String search
    ) {
        if (page < 0) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "Page cannot be negative"
            );
        }

        if (size < 1 || size > 200) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Page size must be between 1 and 200"
            );
        }

        CachedCsv csv = load(filename);
        String query = search == null
                ? "" : search.toLowerCase(Locale.ROOT).trim();

        List<List<String>> matching = query.isEmpty()
                ? csv.rows()
                : csv.rows().stream()
                    .filter(row -> row.stream().anyMatch(value ->
                            value.toLowerCase(Locale.ROOT)
                                    .contains(query)))
                    .toList();

        long total = matching.size();
        int totalPages = (int) ((total + size - 1) / size);
        long start = (long) page * size;

        List<List<String>> rows = start >= total
                ? List.of()
                : matching.subList(
                        (int) start,
                        (int) Math.min(start + size, total)
                );

        return new CsvPage(
                filename, csv.headers(), rows,
                total, page, size, totalPages
        );
    }
}
