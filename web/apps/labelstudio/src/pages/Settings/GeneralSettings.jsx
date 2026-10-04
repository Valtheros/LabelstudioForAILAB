import { Button } from "@humansignal/ui";
import { useContext } from "react";
import { Form, Input, TextArea } from "../../components/Form";
import { RadioGroup } from "../../components/Form/Elements/RadioGroup/RadioGroup";
import { ProjectContext } from "../../providers/ProjectProvider";

export const GeneralSettings = () => {
  const { project, fetchProject } = useContext(ProjectContext);
  if (!project.id) return null;
  return <div className="general-settings"><div className="general-settings__wrapper">
    <h1>General Settings</h1>
    <div className="settings-wrapper">
      <Form action="updateProject" formData={project} params={{pk: project.id}} onSubmit={() => fetchProject(project.id, true)}>
        <Form.Row columnCount={1} rowGap="16px">
          <Input name="title" label="Project Name" />
          <TextArea name="description" label="Description" style={{minHeight:128}} />
          <RadioGroup label="Task Sampling" name="sampling" simple>
            <RadioGroup.Button value="Sequential sampling" label="Sequential" />
            <RadioGroup.Button value="Uniform sampling" label="Random" />
          </RadioGroup>
        </Form.Row>
        <Form.Actions><Form.Indicator><span case="success">Saved!</span></Form.Indicator><Button type="submit" aria-label="Save general settings">Save</Button></Form.Actions>
      </Form>
    </div>
  </div></div>;
};
GeneralSettings.menuItem = "General";
GeneralSettings.path = "/";
GeneralSettings.exact = true;
