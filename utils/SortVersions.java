import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import org.apache.maven.artifact.versioning.ComparableVersion;

/** Batch sorting with the Maven implementation shipped with this repository. */
class SortVersions {
    public static void main(String[] args) throws Exception {
        var versions = new ArrayList<String>();
        var reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = reader.readLine()) != null) {
            versions.add(line);
        }
        versions.sort(Comparator.comparing(ComparableVersion::new).reversed()
            .thenComparing(Comparator.naturalOrder()));
        versions.forEach(System.out::println);
    }
}
