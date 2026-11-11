import PagePlaceholder from "../../../components/ui/PagePlaceholder.jsx";

export default function PayrollPage() {
  return (
    <PagePlaceholder
      title="Planillas y retenciones"
      description="Cálculo de planilla por país y frecuencia. Las retenciones legales (porcentaje, tramos o monto fijo, con topes y vigencias) se configuran como datos."
      tables={["fin.Payroll", "fin.PayrollDetail", "fin.PayrollDeduction", "fin.catDeductionType", "fin.DeductionBracket"]}
    />
  );
}
