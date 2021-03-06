from django.shortcuts import redirect, render
from .forms import PatientForm, DVHDumpForm, PatientNameForm
from .pyTG43.pyTG43 import *
from .oncprost_utilities.oncprost_utilities import *
from django.conf import settings
import dicom
import os
from scipy.interpolate import interp1d
import json

def index(request):
    """
    Render home page, which just has a search
    box for Patient ID's in it.
    """
    if request.method == "POST":
        if 'search_by_id' in request.POST:
            id_form = PatientForm(request.POST)    #create form
            if id_form.is_valid():
                post = id_form.save(commit=False)
                patient_ID = post
                patient_ID.patient_ID = patient_ID.patient_ID.upper()   #convert ID to uppercase
                return redirect('view_patient',patient_ID=patient_ID)
        elif 'search_by_name' in request.POST:
            name_form = PatientNameForm(request.POST)
            if name_form.is_valid():
                post = name_form.save(commit=False)
                patient_name = post
                patient_name = "%"+patient_name.patient_name.upper().replace(' ','%')+"%"   #convert ID to uppercase
                return redirect('view_ids',patient_name=patient_name)
    else:
        id_form = PatientForm()      #remove default ID in production
        name_form = PatientNameForm()      #remove default ID in production initial={'patient_name': 'white'}
    return render(request, 'myapp/index.html',  {'id_form': id_form,
                                                 'name_form':name_form})

def parse_patient_name(name_raw):
    name_raw = name_raw.split('^')
    for i in range(1,len(name_raw)):
        name_raw[i] = name_raw[i].title()
    name_raw = ' '.join(name_raw).rstrip()
    return name_raw

def view_patient(request, patient_ID):
    """
    Produces view for list of cases associated with patient ID
    """
    available_cases = get_patient_studies(patient_ID)
    if available_cases == []:  # If I couldn't find any cases, through an error page
        return render(request, 'myapp/error_cases_not_found.html',{})
    else:
        patient_name = parse_patient_name(get_patient_name(patient_ID))
        return render(request, 'myapp/view_patient.html',  {'patient_ID':patient_ID,
                                                            'patient_name':patient_name,

                                                            'cases':sorted(available_cases)})
def view_ids(request, patient_name):
    """
    Produces view for list of cases associated with patient ID
    """
    patient_IDs, patient_names = get_patient_IDs_and_names(patient_name)
    # patient_names = get_patient_names(patient_name)
    patient_names = [parse_patient_name(x) for x in patient_names]
    list_of_results = []
    for i in range(len(patient_IDs)):
        temp_dict = {}
        temp_dict['patient_id'] = patient_IDs[i]
        temp_dict['patient_name'] = patient_names[i]
        list_of_results.append(temp_dict)
    if patient_IDs == []:  # If I couldn't find any cases, through an error page
        return render(request, 'myapp/error_patient_not_found.html',{})
    else:
        return render(request, 'myapp/view_ids.html',  {'results':list_of_results})


def view_case(request, patient_ID, case_label):
    """
    Lists plans available for that case
    """
    available_plans, raw_plan_names = get_plans_from_study(patient_ID, case_label)
    patient_name = parse_patient_name(get_patient_name(patient_ID))
    return render(request, 'myapp/view_case.html',  {'patient_ID':patient_ID,
                                                     'patient_name':patient_name,
                                                     'case_label':case_label,
                                                        'plans':available_plans})

def view_plan(request, patient_ID, case_label, plan_name):
    """
    Open up some basic details of the plan + give user option to
    make protocol or run dose check
    """
    try:
        #my_plan = fetch_plan(patient_ID, case_label, plan_name)
        patient_ID =  patient_ID.split('/')[0]
        patient_name = parse_patient_name(get_patient_name(patient_ID))
        # import ipdb; ipdb.set_trace()
        return render(request, 'myapp/view_plan.html',  {'patient_ID':patient_ID,
                                                         'case_label':case_label,
                                                         'patient_name':patient_name,
                                                         'plan_name':plan_name,
                                                         })
    except:
        return render(request, 'myapp/error_parse_plan.html',{'patient_ID':patient_ID,
                                                         'case_label':case_label})


def view_protocol(request, patient_ID, case_label, plan_name):
    """
    Create basic HTML with protocol details. Have to do
    stupid reformatting of the data before passing it to
    template because Jinja2 + Django = annoying limits on
    accessing lists indexes.
    """
    try:
        plan_number =  plan_name.split(' ')[1]
        my_plan, my_POIs = fetch_plan(patient_ID, case_label, plan_number)

        patient_name = parse_patient_name(get_patient_name(patient_ID))
        my_plan['patient_name'] = patient_name
        my_plan['plan_name'] = plan_name
        insert_list = []
        for i in range(len(my_plan['channels'])):
            temp_dict = {}
            # temp_dict['channel_name'] = my_plan.channel_names[1+i]
            temp_dict['channel_number'] = my_plan['channels'][i]['channel_number']
            temp_dict['channel_time_total'] = round( my_plan['channels'][i]['channel_time_total'],1)
            temp_dict['reference_length'] = my_plan['channels'][i]['reference_length']
            temp_dict['step_size'] = my_plan['channels'][i]['step_size']
            dwells = []
            for j in range(len(my_plan['sources']['dwell_times'])):
                dwell_dict = {}
                if my_plan['sources']['channel_number'][j] == my_plan['channels'][i]['channel_number']:
                    dwell_dict['dwell_time'] = round(my_plan['sources']['dwell_times'][j],1)
                    dwell_dict['dwell_position'] = my_plan['sources']['dwell_positions'][j]
                    dwells.append(dwell_dict)
            temp_dict['dwells'] = dwells
            insert_list.append(temp_dict)
        # my_plan.prescription = "{0:.2f}".format(my_plan.prescription)
        # import ipdb; ipdb.set_trace()
        return render(request, 'myapp/view_protocol.html',  {'plan':my_plan,
                                                             'case_label':case_label,
                                                             'patient_name':patient_name,
                                                             'plan_data':insert_list,
                                                             })
    except:
        return render(request, 'myapp/error_parse_plan.html',{'patient_ID':patient_ID,
                                                         'case_label':case_label})


def dose_check(request, patient_ID, case_label, plan_name):
    """
    Perform dose check and render results page
    """
    try:
        plan_number =  plan_name.split(' ')[1]
        plan_data_dict, my_POIs = fetch_plan(patient_ID, case_label, plan_number)
        plan_data_dict['POIs'] = []
        plan_data_dict['POI_names'] = []
        op_poi_doses = []
        for k in range(len(my_POIs)):
            plan_data_dict['POIs'].append([0.1*float(x) for x in my_POIs[k][1].split(':')])
            plan_data_dict['POI_names'].append(my_POIs[k][0])
            op_poi_doses.append(my_POIs[k][2])

        my_source_train = []
        for i in range(len(plan_data_dict['sources']['coordinates'])):
            my_source_train.append(SourcePosition(x=plan_data_dict['sources']['coordinates'][i][0],
                                                  y=plan_data_dict['sources']['coordinates'][i][1],
                                                  z=plan_data_dict['sources']['coordinates'][i][2],
                                                  dwell_time=plan_data_dict['sources']['dwell_times'][i],
                                                  apparent_activity=10,
                                                  Sk=40820,
                                                  dose_rate_constant=1.109,
                                                  L=0.36,
                                                  t_half=73.83))
        #reformat results into a list of dictionaries due to limitations in Jinja2
        insert_list = []
        idx = 0
        for point in plan_data_dict['POIs']:
            temp_dict = {}
            temp_dict['x_coord'] = round(point[0],2)
            temp_dict['y_coord'] = round(point[1],2)
            temp_dict['z_coord'] = round(point[2],2)
            temp_dict['poi_name'] = plan_data_dict['POI_names'][idx]

            my_dose = calculate_dose(my_source_train, point)  #perform dose calculation

            temp_dict['pyTG43_dose'] = round(my_dose,2)
            temp_dict['OP_dose'] = round(op_poi_doses[idx],2)
            temp_dict['perc_difference'] = round(100*((op_poi_doses[idx]/my_dose)-1),2)

            insert_list.append(temp_dict)
            idx += 1
        context_data = {'patient_ID':patient_ID,
                          'case_label':case_label,
                           'plan_name':plan_name,
                           'calc_data':insert_list}
        return render(request, 'myapp/dose_check.html',  context_data)
    except:
        return render(request, 'myapp/error_parse_plan.html',{'patient_ID':patient_ID,
                                                         'case_label':case_label})



def dvh_dump(request):
    if request.method == "POST":
        form = DVHDumpForm(request.POST)
        if form.is_valid():
            try:
                dvh_data, tolerances_json = analyse_dvh(form.data['dump'])
            except:
                return render(request, 'myapp/error_dvh_parse_fail.html',{})
            return render(request, 'myapp/view_dvh.html', {'dvh_data':dvh_data,'tolerances':tolerances_json})
    else:
        form = DVHDumpForm()
    return render(request, 'myapp/dvh_dump.html', {'form': form})


def analyse_dvh(input_data):
    with open(r'myapp/static/myapp/tolerances.json') as data_file:
        tolerances_json = json.load(data_file)
    raw_ROIs = input_data.split('ROI')
    prescription = 7.1
    ROI_dict = {}
    for ROI in raw_ROIs[2:]:
        temp_dict = {}
        temp_dict['bin'] = []
        temp_dict['dose'] = []
        temp_dict['volume'] = []
        for i in range(len(ROI.split('\n')[4:-3])):
            temp_dict['bin'].append(int(ROI.split('\n')[4:-3][i].split('\t')[0]))
            temp_dict['dose'].append(float(ROI.split('\n')[4:-3][i].split('\t')[1]))
            temp_dict['volume'].append(float(ROI.split('\n')[4:-3][i].split('\t')[2]))
        temp_dict['volume_cc'] = round(float(temp_dict['volume'][0]),2)
        ROI_dict[ROI.split('***')[0].split('\n')[0][2:].split('\r')[0].replace('-','')] = temp_dict
    for ROI in ROI_dict:
        # import ipdb; ipdb.set_trace()
        f = interp1d(ROI_dict[ROI]['volume'],ROI_dict[ROI]['dose'])
        try:
            ROI_dict[ROI]['D2cc'] = {}
            ROI_dict[ROI]['D2cc']['value'] = round(float(f(2)),2)
            ROI_dict[ROI]['D2cc']['result'] = ''
            ROI_dict[ROI]['D2cc']['result'] = ('fail', 'pass')[eval('ROI_dict[ROI][\'D2cc\'][\'value\']'+tolerances_json[ROI]['D2cc']['math']+'float(tolerances_json[ROI][\'D2cc\'][\'value\'])')]
        except:
            pass
        try:
            ROI_dict[ROI]['D90'] = {}
            ROI_dict[ROI]['D90']['value'] = round(float(f(0.9*ROI_dict[ROI]['volume_cc'])),2)
            ROI_dict[ROI]['D90']['result'] = ''
            ROI_dict[ROI]['D90']['result'] = ('fail', 'pass')[eval('ROI_dict[ROI][\'D90\'][\'value\']'+tolerances_json[ROI]['D90']['math']+'float(tolerances_json[ROI][\'D90\'][\'value\'])')]
        except:
            pass
        f = interp1d(ROI_dict[ROI]['dose'],ROI_dict[ROI]['volume'])
        try:
            ROI_dict[ROI]['V100'] = {}
            ROI_dict[ROI]['V100']['value'] = round(float(100*(f(prescription)/ROI_dict[ROI]['volume_cc'])),2)
            ROI_dict[ROI]['V100']['result'] = ''
            ROI_dict[ROI]['V100']['result'] = ('fail', 'pass')[eval('ROI_dict[ROI][\'V100\'][\'value\']'+tolerances_json[ROI]['V100']['math']+'float(tolerances_json[ROI][\'V100\'][\'value\'])')]
        except:
            pass
        try:
            ROI_dict[ROI]['V67'] = {}
            ROI_dict[ROI]['V67']['value'] = round(float(100*(f(0.67*prescription)/ROI_dict[ROI]['volume_cc'])),2)
            ROI_dict[ROI]['V67']['result'] = ''
            ROI_dict[ROI]['V67']['result'] = ('fail', 'pass')[eval('ROI_dict[ROI][\'V67\'][\'value\']'+tolerances_json[ROI]['V67']['math']+'float(tolerances_json[ROI][\'V67\'][\'value\'])')]
        except:
            pass
    ROI_dict['patient_name'] = raw_ROIs[0].split('\r')[0].split('Patient: ')[1]
    ROI_dict['patient_ID'] = raw_ROIs[0].split('\r')[1].split('Patient Id: ')[1]
    ROI_dict['case_label'] = raw_ROIs[0].split('\r')[2].split('Case: ')[1]
    ROI_dict['plan_name'] = raw_ROIs[0].split('\r')[3].split('Plan: ')[1]
    return ROI_dict, tolerances_json
