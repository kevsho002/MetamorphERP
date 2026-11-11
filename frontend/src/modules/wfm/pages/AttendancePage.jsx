import PagePlaceholder from "../../../components/ui/PagePlaceholder.jsx";

export default function AttendancePage() {
  return (
    <PagePlaceholder
      title="Asistencias y downtimes"
      description="Marcaciones diarias e ingesta paramétrica desde WFM externos: el mapeo de columnas y de códigos AUX se configura por origen, sin cambiar código."
      tables={[
        "wfm.Attendance",
        "wfm.AttendanceDowntime",
        "wfm.catDowntimeType",
        "wfm.catIngestionSource",
        "wfm.IngestionFieldMap",
        "wfm.DowntimeCodeMap",
        "wfm.IngestionBatch",
        "wfm.IngestionBatchError",
      ]}
    />
  );
}
