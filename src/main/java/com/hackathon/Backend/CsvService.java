
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

        List<List<String>> matching;

        if (query.isEmpty()) {
            matching = csv.rows();
        } else {
            // Split the query into terms so a multi-word search ranks
            // rows that match more terms (and match them more often) higher.
            String[] terms = query.split("\\s+");

            matching = csv.rows().stream()
                    .map(row -> Map.entry(
                            row, relevanceScore(row, csv.headers(), terms)))
                    .filter(entry -> entry.getValue() > 0)
                    // Highest relevance first; stable sort preserves the
                    // original file order for rows with equal scores.
                    .sorted(Comparator.comparingDouble(
                            (Map.Entry<List<String>, Double> e) ->
                                    e.getValue()).reversed())
                    .map(Map.Entry::getKey)
                    .toList();
        }

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

    /**
     * Scores how relevant a row is to the search terms. A row scores points
     * for each term it contains, weighted so that matches in the more
     * meaningful columns (title, company, matched_skills, location) count
     * more than matches buried in the description. A row that matches more
     * of the terms also scores higher. Returns 0 when no term matches.
     */
    private double relevanceScore(
            List<String> row, List<String> headers, String[] terms) {

        double score = 0;

        for (String term : terms) {
            if (term.isEmpty()) {
                continue;
            }

            boolean termMatched = false;

            for (int i = 0; i < row.size(); i++) {
                String value = row.get(i).toLowerCase(Locale.ROOT);

                if (!value.contains(term)) {
                    continue;
                }

                termMatched = true;

                String column = i < headers.size()
                        ? headers.get(i).toLowerCase(Locale.ROOT)
                        : "";

                double weight = columnWeight(column);

                // Count every occurrence of the term in this cell so a cell
                // mentioning the term repeatedly ranks above one that mentions
                // it once.
                int occurrences = 0;
                int from = 0;
                while ((from = value.indexOf(term, from)) != -1) {
                    occurrences++;
                    from += term.length();
                }

                score += weight * occurrences;

                // Bonus when the cell equals the term exactly (e.g. an exact
                // company or location match).
                if (value.equals(term)) {
                    score += weight * 5;
                }
            }

            // Reward rows that match more of the distinct search terms.
            if (termMatched) {
                score += 10;
            }
        }

        return score;
    }

    private double columnWeight(String column) {
        return switch (column) {
            case "title" -> 8;
            case "company" -> 6;
            case "matched_skills" -> 5;
            case "location" -> 4;
            case "description" -> 1;
            default -> 2;
        };
    }
}
